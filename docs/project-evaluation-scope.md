# 프로젝트 평가 MVP 범위

## 한 줄 정의

프로젝트 평가 MVP는 지원자가 제출한 문서와 코드를 분석하고, Streamlit 기반 단계형 인터뷰와 선택적 오디오 녹음을 통해 지원자가 실제로 해당 프로젝트를 수행했는지 검증하는 도구다.

## 제품 목적

이 프로젝트는 일반 학습 평가 플랫폼이 아니다. 목표는 하나다.

> 이 지원자가 이 프로젝트를 진짜로 수행했는가?

따라서 모든 기능은 프로젝트 수행 진위 확인에 직접 기여해야 한다. 강의실, 학교 로그인, 학생/교수자 운영, 일반 시험 관리, 성적 관리, 학습 대시보드 같은 부가 기능은 MVP 범위에서 제외한다.

## 핵심 방향

새 Web 프로젝트로 시작하고, 기존 CLI MVP에서는 다음 core 로직만 이식한다.

- 자료 입력 및 텍스트 추출
- 문서/코드 기반 프로젝트 context 구성
- RAG 기반 질문 생성
- 답변 평가
- 꼬리질문 생성
- Bloom’s Taxonomy 기반 질문 수준 설계
- 루브릭 기반 정량·정성 평가
- 리포트 생성

기존 backend/frontend의 강의실·시험 운영 도메인은 이 제품 목적과 맞지 않으므로 기본 전제로 삼지 않는다.

## MVP 사용자 흐름

```text
지원자 프로젝트 자료 업로드
        ↓
문서/코드 텍스트 추출
        ↓
프로젝트 구조와 핵심 평가 포인트 분석
        ↓
Bloom 단계와 루브릭 기준에 따른 질문 생성
        ↓
Streamlit 기반 단계형 인터뷰 진행
        ↓
답변별 근거 일치도와 수행 진위 평가
        ↓
프로젝트 영역별 상세 리포트 생성
```

## 입력 자료

MVP는 프로젝트 자료를 **단일 zip 파일**로 받는다.

zip 내부에는 문서와 코드를 모두 포함할 수 있다.

### zip 내부 코드 자료

- 프로젝트 소스 코드
- README
- API 명세
- 설정 파일

### zip 내부 문서 자료

- PDF 보고서
- PPTX 발표자료
- DOCX 설계 문서
- 프로젝트 설명 텍스트

GitHub URL 직접 분석과 개별 파일 업로드는 현 MVP 범위에서 제외한다.

zip 내부 자료는 코드와 프로젝트 문서가 섞여 들어오므로, 분석 단계에서 role별로 분류한다. role 분류와 RAG 처리 상세는 `docs/rag-ingestion-and-retrieval.md`를 따른다.

## 자료 분석 범위

업로드된 문서와 코드에서 다음 정보를 추출한다.

- 프로젝트 목적
- 주요 기능
- 기술 스택
- 아키텍처 구조
- 핵심 모듈
- 데이터 흐름
- API 흐름
- 저장소/DB/외부 연동 구조
- 구현 난이도가 높은 부분
- 지원자가 직접 설명해야 할 설계 의사결정
- 문서와 코드 사이의 불일치 가능 지점
- 구현 흐름과 제출 문서 주장 사이의 alignment
- 질문과 리포트에 연결될 source refs
- 검증 질문으로 이어질 수 있는 위험 지점

## 질문 생성 원칙

질문은 일반 면접 질문이 아니라, 제출 자료를 실제로 구현한 사람만 구체적으로 답하기 쉬운 질문이어야 한다. 질문 생성은 일부 파일이나 상위 N개 artifact 발췌에 의존하지 않고, 사용 가능한 source ref path를 포함한 RAG context pack을 사용한다.

코드 근거와 문서 근거를 함께 포함하는 것은 선호 조건이다. 두 근거를 모두 사용할 수 있으면 문서-코드 alignment를 검증하는 질문을 우선 생성한다. 다만 code-only, docs-only, overview-only RAG 근거만 있다는 이유만으로 실패 처리하지 않으며, 각 질문은 사용 가능한 source ref path 중 1개 이상을 포함해야 한다.

질문은 단일 파일을 고립적으로 설명하게 하기보다 구현 흐름, 모듈 연결, 설계 의사결정, 문서-코드 alignment, 트러블슈팅, 한계 인식을 검증해야 한다.

### 질문 유형

1. **구현 경로 질문**
   - 예: “자료 업로드 후 질문 생성까지 데이터가 어떤 순서로 흐르나요?”
2. **설계 의사결정 질문**
   - 예: “왜 이 벡터 저장소나 RAG 구조를 선택했나요?”
3. **코드/모듈 설명 질문**
   - 예: “이 기능은 어느 모듈에서 시작해 어떤 계층을 거쳐 처리되나요?”
4. **트러블슈팅 질문**
   - 예: “텍스트 추출이 실패하면 어떤 문제가 생기고 어떻게 처리했나요?”
5. **한계 인식 질문**
   - 예: “현재 구현에서 가장 취약한 부분은 무엇이고 어떻게 개선하겠나요?”
6. **변경 요청 질문**
   - 예: “zip 업로드 대신 GitHub URL 분석을 추가하려면 어디를 바꿔야 하나요?”

## Bloom’s Taxonomy 적용

Bloom’s Taxonomy는 학습 평가용 부가 기능이 아니라, 프로젝트 수행 진위 검증 질문의 깊이를 설계하기 위한 프레임으로 유지한다.

| 단계 | 프로젝트 평가에서의 의미 | 질문 예시 |
|---|---|---|
| Remember | 사용한 기술과 구성요소를 기억하는가 | “프로젝트에서 사용한 주요 라이브러리는 무엇인가요?” |
| Understand | 구조와 흐름을 설명할 수 있는가 | “업로드된 자료가 질문 생성에 쓰이기까지의 흐름을 설명해주세요.” |
| Apply | 구현 상황에 지식을 적용할 수 있는가 | “새 파일 형식을 추가하려면 어느 부분을 수정해야 하나요?” |
| Analyze | 모듈 간 관계와 원인을 분석할 수 있는가 | “검색 품질이 낮아질 때 원인을 어디서 찾겠나요?” |
| Evaluate | 설계 선택의 장단점을 판단할 수 있는가 | “현재 RAG 구조의 한계와 대안을 비교해주세요.” |
| Create | 개선 구조를 제안할 수 있는가 | “이 프로젝트를 확장한다면 어떤 구조로 재설계하겠나요?” |

## 루브릭 기반 평가

각 답변은 루브릭으로 평가한다. 점수는 최종 판정의 근거로 쓰며, 단순 총점보다 프로젝트 영역별 신뢰도 분석이 중요하다.

### 기본 루브릭

| 항목 | 의미 |
|---|---|
| 자료 근거 일치도 | 답변이 제출 자료와 일치하는가 |
| 구현 구체성 | 실제 구현 단계, 파일, 흐름, 예외 상황을 구체적으로 설명하는가 |
| 구조 이해도 | 아키텍처와 모듈 간 관계를 이해하는가 |
| 의사결정 이해도 | 왜 그렇게 구현했는지 설명할 수 있는가 |
| 트러블슈팅 경험 | 직접 구현하며 겪을 법한 문제와 해결책을 말하는가 |
| 한계 인식 | 현재 구현의 약점과 개선 방향을 현실적으로 설명하는가 |
| 답변 일관성 | 앞뒤 답변이 서로 모순되지 않는가 |

## 인터뷰 방식

1차 MVP는 Streamlit 기반 단계형 인터뷰를 제공한다.

```text
AI가 질문 텍스트를 제시
        ↓
필요하면 TTS로 질문 음성 재생
        ↓
지원자가 텍스트 또는 오디오 녹음으로 답변
        ↓
오디오 답변은 STT로 답변 텍스트화
        ↓
LLM이 답변 평가
        ↓
필요하면 꼬리질문 생성
        ↓
다음 질문 또는 꼬리질문 표시
```

완전한 실시간 WebRTC 음성 대화는 MVP 이후 고도화 후보로 둔다.

## 최종 판정 방식

최종 판정은 인터뷰 실무형 표현을 사용한다.

- 검증 통과
- 추가 확인 필요
- 신뢰 낮음

단순 판정으로 끝내지 않고, 프로젝트 각 부분에 대한 상세 분석을 제공해야 한다.

## 리포트 구조

리포트는 최소한 다음 내용을 포함한다.

- 최종 판정
- 종합 요약
- 전체 수행 진위 신뢰도
- 프로젝트 영역별 분석
- 질문별 답변 평가
- 질문별 루브릭 점수
- Bloom 단계별 도달도
- 자료 근거와 답변의 일치/불일치
- 질문과 평가에 사용된 source refs / evidence refs
- 의심 지점
- 강점
- 추가 확인 질문

### 프로젝트 영역별 분석 예시

```text
1. 자료 처리 / 데이터 추출
- 판정: 검증 통과
- Bloom 도달도: Analyze
- 루브릭 점수: 18 / 20
- 근거: PDF 파싱, chunking, embedding 흐름을 구체적으로 설명함.
- 의심 지점: OCR 실패 케이스 설명은 부족함.
- 추가 확인 질문: chunk 크기를 어떻게 정했고 검색 품질에 어떤 영향을 줬나요?

2. RAG / 질문 생성
- 판정: 추가 확인 필요
- Bloom 도달도: Evaluate
- 루브릭 점수: 16 / 25
- 근거: Qdrant 사용 이유는 설명했지만 prompt 구성 기준이 불명확함.
- 의심 지점: 질문 생성 품질 개선 경험을 추가 확인해야 함.
- 추가 확인 질문: 검색된 context가 부족할 때 질문 생성 품질을 어떻게 보정했나요?
```

## 최소 화면

### 1. 프로젝트 업로드 화면

- 프로젝트 이름
- 지원자 또는 팀 이름
- 프로젝트 설명
- 프로젝트 자료 zip 업로드
- 평가 시작 버튼

### 2. 분석 결과 화면

- 프로젝트 요약
- 감지된 기술 스택
- 주요 기능
- 핵심 모듈
- 평가 포인트
- 질문 후보

### 3. 단계형 인터뷰 화면

- AI 음성 질문 상태
- STT 인식 상태
- 현재 질문 텍스트
- 지원자 답변 transcript
- 대화 히스토리
- 꼬리질문
- 인터뷰 종료 버튼

### 4. 상세 리포트 화면

- 최종 판정
- 프로젝트 영역별 신뢰도
- 질문별 점수
- Bloom 단계별 분석
- 루브릭 근거
- 의심 지점
- 추가 검증 질문

## 최소 도메인 모델

```text
ProjectEvaluation
ProjectArtifact
ExtractedProjectContext
ProjectArea
InterviewQuestion
InterviewSession
InterviewTurn
RubricScore
EvaluationReport
```

### ProjectEvaluation

프로젝트 평가 하나를 의미한다.

```text
id
project_name
candidate_name
description
status
created_at
```

### ProjectArtifact

업로드된 문서 또는 코드 자료다.

```text
id
evaluation_id
source_type        # zip | extracted_document | extracted_code | text
file_name
source_url
raw_text
status
created_at
```

### ExtractedProjectContext

자료에서 추출한 구조화된 프로젝트 정보다.

```text
id
evaluation_id
summary
tech_stack
features
architecture_notes
data_flow
risk_points
question_targets
```

### ProjectArea

리포트에서 별도로 분석할 프로젝트 영역이다.

```text
id
evaluation_id
name               # 예: 자료 처리, RAG, 백엔드 API, 프론트엔드 상태관리
description
source_refs
```

### InterviewQuestion

자료 기반으로 생성된 질문이다.

```text
id
evaluation_id
project_area_id
question
intent
bloom_level
rubric_criteria
source_artifact_ids
expected_signal
difficulty
```

### InterviewSession

실제 인터뷰 진행 세션이다.

```text
id
evaluation_id
status
started_at
ended_at
```

### InterviewTurn

질문, 답변, 꼬리질문 기록이다.

```text
id
session_id
question_id
role
content
transcript
created_at
```

### RubricScore

질문 또는 답변 단위 루브릭 점수다.

```text
id
turn_id
criterion
score
max_score
reasoning
evidence_refs
```

### EvaluationReport

최종 프로젝트 수행 검증 리포트다.

```text
id
evaluation_id
session_id
final_decision      # verified | needs_followup | low_confidence
authenticity_score
summary
area_analyses
strengths
suspicious_points
recommended_followups
created_at
```

## 최소 API

```text
POST   /api/project-evaluations
GET    /api/project-evaluations/{evaluation_id}

POST   /api/project-evaluations/{evaluation_id}/artifacts/zip

POST   /api/project-evaluations/{evaluation_id}/extract
GET    /api/project-evaluations/{evaluation_id}/context

POST   /api/project-evaluations/{evaluation_id}/questions/generate
GET    /api/project-evaluations/{evaluation_id}/questions

POST   /api/project-evaluations/{evaluation_id}/sessions
POST   /api/project-evaluations/{evaluation_id}/sessions/{session_id}/turns
POST   /api/project-evaluations/{evaluation_id}/sessions/{session_id}/complete

GET    /api/project-evaluations/{evaluation_id}/reports/{report_id}
```

Streamlit 단계형 인터뷰 API는 구현 단계에서 별도 설계한다. 완전한 실시간 STT/TTS 세션용 WebSocket/Realtime 연결은 MVP 이후 고도화 후보로 둔다.

## 제외 범위

다음은 MVP에서 제외한다.

- manyfast 기반 기획
- 강의실
- 학생/교수자 역할 관리
- 학교 로그인
- 일반 시험 생성
- 성적 관리
- 학습 대시보드
- 재응시 정책
- 관리자 비밀번호 기반 방 관리
- 복잡한 권한 시스템
- 화상 감독
- 여러 지원자 비교
- 리포트 PDF export

## 구현 전략

권장 전략은 다음과 같다.

```text
새 Web 프로젝트 생성
+ 기존 CLI의 자료 추출 / 질문 생성 / 평가 / 리포트 core만 이식
```

이유:

- 기존 backend/frontend에는 이 제품에 불필요한 도메인이 많다.
- 현재 제품은 학습 플랫폼이 아니라 프로젝트 수행 진위 검증 도구다.
- CLI MVP의 core 흐름은 유용하지만, Web backend 구조는 목적에 맞게 새로 잡는 편이 빠르다.
- 자료 분석, 질문 생성, 답변 평가, 리포트 생성은 기존 로직을 이식해 재사용한다.
