# API and Job Flow

## 목적

이 문서는 프로젝트 평가 생성부터 최종 리포트까지 FastAPI, BackgroundTasks, Streamlit UI가 공유해야 하는 상태 흐름을 정의한다. Streamlit은 화면과 사용자 입력만 담당하고, 평가 생성·자료 분석·질문 생성·답변 평가·리포트 생성은 FastAPI가 authoritative backend로 수행한다.

## End-to-end flow

```text
1. Streamlit이 프로젝트 정보와 zip 파일을 제출한다.
2. FastAPI가 ProjectEvaluation과 ProjectArtifact를 생성한다.
3. FastAPI background job이 zip을 안전하게 해제한다.
4. 추출된 파일을 artifact role로 분류한다.
5. role별 splitter가 chunk를 만든다.
6. Qdrant에 embedding과 metadata payload를 저장한다.
7. RAG retrieval로 project context와 question context pack을 만든다.
8. LLM이 자료 기반 질문을 생성한다.
9. Streamlit이 단계형 인터뷰를 진행한다.
10. FastAPI가 답변 평가와 꼬리질문 생성을 수행한다.
11. 인터뷰 종료 후 FastAPI가 최종 리포트를 생성한다.
12. Streamlit이 프로젝트 영역별 리포트를 표시한다.
```

## Job 상태 전이

권장 상태는 다음과 같다.

```text
created
  -> zip_uploaded
  -> extracting
  -> indexing
  -> context_ready
  -> questions_ready
  -> interviewing
  -> report_generating
  -> completed
```

모든 장기 처리 단계는 실패 시 `failed`로 전이될 수 있다.

```text
extracting -> failed
indexing -> failed
context_ready -> failed
questions_ready -> failed
report_generating -> failed
```

## 상태별 의미

| 상태 | 의미 | UI 표시 |
|---|---|---|
| `created` | 평가 row가 생성됨 | 프로젝트 생성 완료 |
| `zip_uploaded` | 원본 zip 저장 완료 | 업로드 완료 |
| `extracting` | zip 해제와 텍스트 추출 진행 중 | 자료 추출 중 |
| `indexing` | splitter와 Qdrant ingest 진행 중 | RAG 인덱싱 중 |
| `context_ready` | 프로젝트 context 생성 완료 | 분석 요약 표시 가능 |
| `questions_ready` | 질문 생성 완료 | 인터뷰 시작 가능 |
| `interviewing` | 질문/답변 turn 저장 중 | 현재 질문 표시 |
| `report_generating` | 최종 리포트 생성 중 | 리포트 생성 중 |
| `completed` | 리포트까지 완료 | 리포트 표시 |
| `failed` | 복구가 필요한 실패 | 실패 원인과 확인 대상 표시 |

## 실패 payload

실패는 성공처럼 위장하지 않는다. API와 job row에는 다음 정보를 남긴다.

```json
{
  "status": "failed",
  "failed_phase": "indexing",
  "user_message": "RAG 인덱스를 생성하지 못했습니다.",
  "internal_reason": "Qdrant collection is unavailable",
  "check_targets": ["Qdrant 실행 상태", "collection 설정", "embedding model dimension"],
  "retryable": true
}
```

사용자 메시지는 원인을 숨기지 않되 내부 stack trace나 비밀값을 노출하지 않는다. 내부 로그에는 재현 가능한 입력, phase, source path, dependency 상태를 남긴다.

## 주요 API 흐름

MVP API 흐름은 다음 모양을 기준으로 한다. 실제 route 이름은 구현 시 현재 router 구조에 맞춘다.

```text
POST /api/project-evaluations
POST /api/project-evaluations/{evaluation_id}/artifacts/zip
POST /api/project-evaluations/{evaluation_id}/extract
GET  /api/project-evaluations/{evaluation_id}/status
POST /api/project-evaluations/{evaluation_id}/questions/generate
GET  /api/project-evaluations/{evaluation_id}/questions
POST /api/project-evaluations/{evaluation_id}/interview-sessions
POST /api/project-evaluations/{evaluation_id}/interview-sessions/{session_id}/turns
POST /api/project-evaluations/{evaluation_id}/reports/generate
GET  /api/project-evaluations/{evaluation_id}/report
```

## Streamlit 책임 범위

Streamlit은 다음만 담당한다.

- 프로젝트 이름, 지원자/팀 이름, 설명 입력
- 단일 zip 업로드
- 분석 상태와 실패 메시지 표시
- 질문 텍스트 표시
- 텍스트 답변 입력
- 선택적 오디오 녹음 입력
- transcript 확인
- 인터뷰 turn 진행
- 최종 리포트 표시

Streamlit은 다음을 직접 수행하지 않는다.

- zip 해제
- artifact role classification
- chunking/embedding
- Qdrant ingest/retrieval
- 질문 생성 LLM 호출
- 답변 평가 LLM 호출
- 리포트 생성 LLM 호출
- DB 직접 접근

## FastAPI 책임 범위

FastAPI는 다음의 source of truth다.

- 평가 및 artifact 저장
- zip 안전 해제
- 텍스트 추출
- RAG indexing
- context pack 구성
- 질문 생성
- 답변 평가
- 꼬리질문 생성
- 리포트 생성
- job 상태와 실패 원인 저장

## 상태 API

현재 MVP는 별도 job table을 두지 않고 기존 row에서 derived status를 계산한다.

`GET /api/project-evaluations/{evaluation_id}/status`는 관리자 인증 후 다음 필드를 반환한다.

```json
{
  "evaluation_id": "eval_123",
  "status": "questions_generated",
  "phase": "questions_ready",
  "has_artifacts": true,
  "has_context": true,
  "rag_status": {"status": "indexed", "inserted_count": 128},
  "question_count": 6,
  "expected_question_count": 6,
  "questions_ready": true,
  "can_generate_questions": false,
  "can_join": true,
  "blocked_reason": "",
  "user_message": "질문이 DB에 저장되어 학생 입장이 가능합니다.",
  "check_targets": [],
  "retryable": false
}
```

`phase`는 `created`, `uploaded`, `context_ready`, `rag_not_ready`, `indexing_failed`, `question_count_mismatch`, `questions_ready` 중 하나로 계산된다. Streamlit은 질문 생성 응답만 신뢰하지 않고 이 status와 `GET /questions`를 다시 조회해 DB에 저장된 질문을 authoritative source로 표시한다.

추후 background job을 도입하면 `failed_phase`, `last_error_json`, `retryable`을 job table로 옮기고 status endpoint는 job 상태와 현재 row 상태를 함께 조합한다.

## RAG 상태 표시

분석 결과나 상태 API는 가능한 범위에서 다음 통계를 제공한다.

```json
{
  "inserted_count": 128,
  "code_chunk_count": 72,
  "document_chunk_count": 38,
  "manifest_chunk_count": 18,
  "skipped_count": 4,
  "skipped_reasons": ["binary_file", "empty_text"]
}
```

이 정보는 질문 생성 근거가 충분한지, zip 내부 자료가 대부분 무시되었는지 판단하는 데 사용한다.

## 실패 처리 원칙

- broad `try/except`로 핵심 기능 실패를 성공처럼 처리하지 않는다.
- RAG index가 비어 있으면 질문 생성을 진행하지 않고 실패 상태를 남긴다.
- docs-only 또는 overview-only RAG 근거만 있다는 사실은 실패 조건이 아니다. 유효한 source ref path가 있고 수행 진위 검증 질문을 만들 수 있으면 진행한다.
- 일부 파일 추출 실패는 skipped reason으로 기록하되, 전체 질문 생성이 가능한지 판단 기준을 명확히 둔다.
- 외부 시스템 오류는 retryable 여부를 기록한다.
- 사용자가 직접 수정할 수 있는 입력 문제는 확인 대상을 구체적으로 표시한다.

## 인터뷰 UX 원칙

MVP는 Streamlit 단계형 인터뷰다.

```text
질문 표시
  -> 텍스트 또는 오디오 답변 수집
  -> transcript 제출
  -> 답변 평가
  -> 꼬리질문 또는 다음 질문 표시
```

완전한 실시간 WebRTC 대화는 현 MVP 범위가 아니다.
