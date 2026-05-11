# Security and Data Policy

## 목적

이 문서는 캡스톤 MVP에서 필요한 최소 안전 정책을 정의한다. 목표는 프로덕션급 과잉 보안 체계를 만드는 것이 아니라, 단일 zip 제출과 로컬 시연 과정에서 기본 안전을 해치지 않으면서 프로젝트 수행 진위 검증 기능을 안정적으로 보여주는 것이다.

## 보안 범위

MVP에서는 다음을 우선한다.

- 실제 비밀값 하드코딩 금지
- zip slip과 path traversal 방지
- 과도한 파일 수·크기 입력 방지
- 바이너리·vendor·build output 제외
- 실패 원인 추적 가능성 확보
- 사용자에게 내부 비밀값이나 stack trace 노출 금지

복잡한 인증, 역할 관리, 학교 로그인, 관리자 권한 시스템은 현 MVP 범위가 아니다.

## Zip 처리 안전장치

### 경로 검증

zip member는 해제 전에 다음 조건을 만족해야 한다.

- absolute path가 아니어야 한다.
- `..`로 해제 루트 밖을 가리키지 않아야 한다.
- normalize된 경로가 artifact 저장 루트 내부에 있어야 한다.
- OS별 path separator 차이로 우회되지 않아야 한다.

위 조건을 만족하지 않으면 해당 zip은 실패 처리한다.

### 파일 개수와 크기 제한

MVP에서는 제한값을 설정으로 둔다.

권장 제한:

```text
max_zip_size_mb: 100
max_extracted_size_mb: 300
max_file_count: 3000
max_single_file_size_mb: 20
```

제한을 초과하면 job을 `failed`로 처리하고 사용자에게 초과 항목을 알려준다.

### 중첩 zip

중첩 zip은 현 MVP에서 자동 해제하지 않는다. 중첩 zip이 발견되면 일반 binary/unsupported artifact로 분류하거나 skipped reason을 남긴다.

### 비밀번호 zip

비밀번호로 보호된 zip은 현 MVP에서 지원하지 않는다. 감지되면 명확한 사용자 메시지와 함께 실패 처리한다.

## Ignored path 정책

다음 경로와 파일은 기본적으로 분석에서 제외한다.

```text
.git/
node_modules/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
build/
.next/
.venv/
venv/
coverage/
*.pyc
*.pyo
*.png
*.jpg
*.jpeg
*.gif
*.mp4
*.mov
*.zip
*.tar
*.gz
```

프로젝트의 `.gitignore`가 있으면 `pathspec`으로 반영한다. 다만 README, docs, API spec처럼 평가 근거가 될 수 있는 파일이 과도하게 제외되지 않는지 skipped 통계를 확인한다.

## 허용 분석 범위

우선 분석 대상:

- README, markdown, txt
- Python, TypeScript, JavaScript, Java, Kotlin, Go, Rust 등 주요 source file
- 테스트 코드
- JSON, YAML, TOML 설정 파일
- OpenAPI/Swagger 명세
- PDF 보고서
- PPTX 발표자료
- DOCX 설계 문서

후순위 또는 제외:

- OCR
- 이미지 기반 다이어그램 해석
- 바이너리 파일 분석
- private GitHub repository 연동
- 대용량 monorepo 전체 정밀 static analysis

## 데이터 저장 정책

### 저장 대상

MVP는 로컬 개발과 시연을 기준으로 다음 데이터를 저장한다.

```text
data/app.db                          # SQLite database
data/artifacts/{evaluation_id}/       # 원본 zip과 추출 파일
data/qdrant/ 또는 Qdrant container    # vector payload와 embedding
```

저장되는 데이터:

- 평가 메타데이터
- 원본 zip
- 추출된 텍스트와 artifact metadata
- RAG chunk metadata와 embedding
- 질문과 source refs
- 인터뷰 turn transcript
- 루브릭 점수
- 최종 리포트

### 삭제와 reset

캡스톤 데모에서는 전체 reset 명령 또는 절차를 둔다.

- SQLite database 삭제 또는 초기화
- `data/artifacts/` 삭제
- Qdrant collection 삭제 또는 evaluation_id filter 기반 삭제

특정 평가만 삭제할 때는 SQLite row, artifact directory, Qdrant point를 함께 삭제해야 한다.

## 민감정보 처리

지원자가 제출한 프로젝트 zip에 비밀값이나 개인정보가 들어올 수 있다. MVP는 이를 완전히 탐지한다고 가정하지 않는다.

정책:

- UI와 API 응답에 raw secret 후보를 그대로 강조 표시하지 않는다.
- 오류 메시지에는 환경변수 값, API key, token, stack trace를 포함하지 않는다.
- source refs는 파일 경로와 위치 정보를 제공하되, 필요한 경우 원문 전체 노출은 제한한다.
- 실제 운영으로 확장할 때는 secret scanning과 보관 기간 정책을 별도 강화한다.

## 실패 처리 정책

핵심 기능 실패는 성공처럼 위장하지 않는다.

### 입력 문제

예시:

- zip path traversal
- 비밀번호 zip
- 파일 수 또는 크기 제한 초과
- 분석 가능한 텍스트 없음

처리:

- job status를 `failed`로 둔다.
- 사용자 메시지에 수정 가능한 입력 문제를 명시한다.
- 내부 로그에 실패 phase와 zip member 정보를 남긴다.

### 시스템 의존성 문제

예시:

- Qdrant 연결 실패
- embedding model dimension 불일치
- OpenAI API 호출 실패
- SQLite write 실패

처리:

- job status를 `failed`로 둔다.
- retryable 여부를 기록한다.
- 사용자 메시지는 확인 대상을 제시한다.
- 내부 로그에는 dependency 이름과 재현 가능한 context를 남긴다.

### 부분 실패

일부 파일만 추출 또는 split에 실패할 수 있다.

처리 기준:

- 실패한 파일은 skipped reason을 남긴다.
- 전체 RAG index가 충분하면 진행할 수 있다.
- code/document chunk가 전혀 없거나 질문 근거가 비어 있으면 질문 생성을 중단한다.
- skipped 통계는 분석 상태 API와 UI에서 확인 가능하게 한다.

## 관련 문서

- RAG role과 chunk metadata: `docs/rag-ingestion-and-retrieval.md`
- job 상태와 실패 payload: `docs/api-and-job-flow.md`
- 제품 범위와 제외 범위: `docs/project-evaluation-scope.md`
