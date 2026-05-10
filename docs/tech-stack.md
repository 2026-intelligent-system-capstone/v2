# 기술 스택 선정

## 결정 요약

`v2/`는 기존 강의실/시험 운영 플랫폼을 확장하지 않고, 프로젝트 수행 진위 검증에 필요한 Web 서비스만 새로 만든다. 캡스톤 시연용으로 빠르게 구현하기 위해 기술 스택은 다음으로 고정한다.

- **Backend**: FastAPI
- **Frontend**: Streamlit
- **Relational storage**: SQLite3
- **Vector storage**: Qdrant
- **LLM / STT / TTS**: OpenAI API

선정 기준은 다음과 같다.

1. 기존 `cli/`의 Python 기반 자료 추출, RAG, 질문 생성, 평가, 리포트 core를 최대한 재사용한다.
2. Streamlit으로 빠르게 시연 가능한 UI를 만든다.
3. SQLite3로 별도 DB 운영 없이 평가 상태와 리포트를 저장한다.
4. MVP는 단일 zip 제출, 단계형 인터뷰, 프로젝트 영역별 리포트 생성에 집중한다.
5. manyfast, 강의실, 일반 시험 관리, 학교 로그인, 학습 대시보드 기능은 스택 선택 기준에서 제외한다.

## 전체 아키텍처

```text
Streamlit UI
  ├─ 프로젝트 정보 입력
  ├─ 단일 zip 업로드
  ├─ 분석 상태 표시
  ├─ 질문/답변 단계형 인터뷰
  ├─ 선택적 오디오 녹음 입력
  └─ 프로젝트 영역별 리포트 표시

FastAPI Service
  ├─ 프로젝트 평가 API
  ├─ zip 저장 및 안전한 해제
  ├─ 문서/코드 추출 job 실행
  ├─ RAG context 구성
  ├─ 질문 생성 / 답변 평가 / 꼬리질문 생성
  ├─ 인터뷰 turn 저장
  └─ 최종 리포트 생성

Storage
  ├─ SQLite3: 평가, 자료 메타데이터, 질문, 인터뷰 turn, 점수, 리포트
  ├─ Qdrant: 문서/코드 chunk embedding
  └─ Local artifact storage: 제출 zip, 해제 파일, 추출 원본
```

## Frontend

### 선택

- **Streamlit**
- **requests 또는 httpx**
- **st.session_state**
- **st.file_uploader**
- **st.audio_input**
- **st.chat_input 또는 form 기반 텍스트 입력**

### 역할

Streamlit은 화면과 사용자 입력만 담당한다.

- 프로젝트 업로드 화면
- 분석 진행 상태 화면
- 질문 후보/프로젝트 영역 미리보기
- 단계형 인터뷰 화면
- 텍스트 답변 fallback
- 선택적 오디오 녹음 입력
- 상세 리포트 화면
- FastAPI API 호출

### 선정 이유

- Python 기반이라 기존 CLI core, FastAPI backend와 개발 언어를 통일할 수 있다.
- 캡스톤 시연용 UI를 빠르게 만들 수 있다.
- `st.file_uploader`로 단일 zip 업로드를 구현하기 쉽다.
- `st.session_state`로 현재 평가 ID, 세션 ID, 질문 index, transcript 같은 인터뷰 진행 상태를 관리할 수 있다.
- `st.audio_input`으로 완전한 실시간 WebRTC 없이도 음성 답변 녹음 기반 MVP를 만들 수 있다.

### Streamlit 사용 원칙

- Streamlit은 business logic을 직접 갖지 않는다.
- 모든 평가 생성, 자료 분석, 질문 생성, 답변 평가, 리포트 생성은 FastAPI를 통해 수행한다.
- Streamlit session state에는 UI 진행 상태와 현재 API 응답만 둔다.
- 장기 분석 작업은 Streamlit process에서 직접 실행하지 않는다.
- LLM API key, storage 경로, DB 접근 정보는 Streamlit UI에 노출하지 않는다.

## Backend API

### 선택

- **Python 3.13+**
- **uv**
- **FastAPI**
- **Pydantic v2**
- **SQLAlchemy 2.x**
- **SQLite3**
- **pytest**
- **Ruff**

### 역할

FastAPI는 프로젝트 평가의 authoritative backend다.

- `ProjectEvaluation` 생성 및 조회
- 단일 zip artifact 등록
- zip 안전 해제 및 문서/코드 분리
- artifact 추출 job 시작 및 상태 조회
- `ExtractedProjectContext` 생성
- `ProjectArea` 및 질문 후보 생성
- 인터뷰 세션과 turn 저장
- 답변 평가와 루브릭 점수 저장
- 최종 리포트 생성과 조회

### 선정 이유

- 기존 `cli/` core가 Python으로 되어 있어 로직 이식 비용이 낮다.
- Pydantic 모델을 API contract와 LLM structured output contract 양쪽에 재사용할 수 있다.
- FastAPI의 OpenAPI schema로 API 계약을 빠르게 확인할 수 있다.
- 파일 업로드, background task, async API를 모두 지원한다.

## Background Jobs

### MVP 선택

- **FastAPI BackgroundTasks + SQLite job 상태 테이블**로 시작한다.

### 재검토 기준

아래 조건 중 하나라도 생기면 worker 분리를 재검토한다.

- zip 분석, embedding 생성이 요청 timeout을 자주 넘긴다.
- 동시에 여러 평가를 돌려야 한다.
- 분석 job 재시도, 취소, 진행률 streaming이 필요하다.
- API process 재시작 시 job 유실이 문제가 된다.

### 이유

MVP는 캡스톤 시연과 빠른 구현이 우선이므로 별도 queue 인프라를 처음부터 도입하지 않는다. 다만 분석 작업은 장기 실행 가능성이 높으므로 job 상태 모델은 처음부터 worker 전환이 가능하게 둔다.

## LLM / RAG

### 선택

- **OpenAI API**
- **LangGraph**
- **LangChain core / text splitters / qdrant integration**
- **Qdrant**
- **Pydantic structured models**

### 기존 CLI에서 이식할 core

- `models.py`의 Bloom level, 질문, 평가, 리포트 모델 개념
- `ingest.py`의 자료 추출, chunking, embedding 저장 흐름
- `generate_exam.py`의 LangGraph 기반 질문 생성 흐름
- `exam_core.py`의 답변 평가, 꼬리질문 생성, 리포트 생성 흐름

단, 기존 `ExamConfig`, `subject`, `week`, `professor`, 일반 시험 유형 같은 교육 플랫폼 필드는 프로젝트 평가 도메인에 맞게 재정의한다.

### 모델 사용 원칙

- 질문 생성, 답변 평가, 리포트 생성 모델명은 환경변수로 둔다.
- STT/TTS 모델명도 환경변수로 둔다.
- LLM 출력은 가능하면 Pydantic schema로 검증한다.
- 평가 결과는 최종 점수만 저장하지 않고 evidence reference와 reasoning을 함께 저장한다.

### Qdrant 사용 원칙

- collection은 MVP에서 하나로 시작하되, payload에 `evaluation_id`, `artifact_id`, `project_area`, `source_path`, `chunk_type`을 둔다.
- 문서 chunk와 코드 chunk는 같은 collection에 저장하되 payload로 구분한다.
- 더 빠른 MVP가 필요하면 Qdrant 의존도를 줄이는 local/in-memory retrieval spike를 별도 검토한다.

## Interview UX

### MVP 선택

- **Streamlit 단계형 인터뷰**
- **텍스트 답변 기본 지원**
- **`st.audio_input` 기반 음성 답변 선택 지원**

### 흐름

```text
1. FastAPI가 현재 질문을 반환
2. Streamlit이 질문 텍스트를 표시
3. 필요하면 TTS로 질문 음성을 생성해 재생
4. 학생이 텍스트 또는 오디오로 답변
5. 오디오 답변이면 STT로 transcript 생성
6. Streamlit이 transcript를 FastAPI에 제출
7. FastAPI가 답변 평가와 꼬리질문 필요 여부 판단
8. Streamlit이 다음 질문 또는 꼬리질문을 표시
9. 인터뷰 종료 후 리포트 생성
```

### 설계 결정

- MVP에서 완전한 실시간 WebRTC 대화는 구현하지 않는다.
- Streamlit의 장점인 빠른 시연과 Python 단일 흐름을 우선한다.
- 질문 출력, 답변 수집, 평가, 다음 질문의 단계가 명확한 인터뷰를 만든다.
- 향후 정교한 실시간 음성 UX가 필요하면 별도 Web frontend를 재검토한다.

## Artifact / Text Extraction

### 입력 정책

- 프로젝트 자료는 **단일 zip 파일**로 제출한다.
- zip 내부에는 PDF, PPTX, DOCX, README, API 명세, 프로젝트 코드가 포함될 수 있다.
- GitHub URL 직접 분석과 개별 파일 업로드는 v1 범위에서 제외한다.

### 선택

- **zipfile / pathlib**: zip 업로드 해제와 경로 제어
- **pypdf**: PDF 보고서 추출
- **python-pptx**: 발표자료 추출
- **python-docx**: 문서 추출
- **pathspec**: `.gitignore` 기반 코드 파일 필터링

### MVP 분석 범위

- README, markdown, txt
- Python, TypeScript, JavaScript, Java, Kotlin, Go 등 주요 source file
- PDF 보고서
- pptx 발표자료
- docx 설계 문서
- OpenAPI/Swagger JSON 또는 YAML

### 제외 또는 후순위

- OCR
- 이미지 기반 다이어그램 해석
- 바이너리 파일 분석
- private GitHub repository 연동
- 대용량 monorepo 전체 정밀 static analysis

## Database / Persistence

### 선택

- **SQLite3**
- **SQLAlchemy 2.x**

### 저장 대상

- `ProjectEvaluation`
- `ProjectArtifact`
- `ExtractedProjectContext`
- `ProjectArea`
- `InterviewQuestion`
- `InterviewSession`
- `InterviewTurn`
- `RubricScore`
- `EvaluationReport`
- 분석 job 상태

### SQLite 사용 원칙

- SQLite 파일은 로컬 `data/app.db` 같은 고정 경로에 둔다.
- 업로드 artifact는 `data/artifacts/{evaluation_id}/` 아래에 저장한다.
- 데모 reset을 위해 DB와 artifact 디렉터리를 초기화하는 명령을 둔다.
- Alembic은 후순위로 두고, MVP 초기에는 SQLAlchemy `create_all` 또는 가벼운 init script로 시작할 수 있다.
- 동시 다중 사용자 운영은 목표가 아니므로 SQLite 동시성 한계는 MVP 리스크로 수용한다.

### 이유

- 별도 PostgreSQL 컨테이너 없이 빠르게 실행할 수 있다.
- 캡스톤 시연 환경에서 설치와 운영 부담이 낮다.
- 단일 교수/단일 시연 플로우에는 충분하다.
- 추후 운영화가 필요하면 PostgreSQL로 전환할 수 있도록 repository boundary를 유지한다.

## Local Development

### 선택

- **FastAPI local server**
- **Streamlit local app**
- **SQLite3 local file**
- **Qdrant container 또는 local Qdrant 실행**

### 패키지 매니저

- Backend/API: **uv**
- Streamlit app: **uv workspace 또는 동일 Python project**

### 기본 명령 방향

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format .
uv run uvicorn app.main:app --reload
uv run streamlit run apps/streamlit/Home.py
```

## Testing

### Backend

- pytest unit tests
- FastAPI TestClient 또는 httpx 기반 API integration tests
- SQLite temporary database fixture
- LLM 호출은 기본적으로 fake adapter로 격리
- Pydantic schema validation tests
- artifact extraction fixture tests
- report generation golden snapshot tests

### Streamlit

- 핵심 business logic은 Streamlit이 아니라 FastAPI/service layer에서 테스트한다.
- Streamlit은 smoke test와 수동 시연 체크리스트 중심으로 검증한다.
- 필요하면 Playwright로 Streamlit golden path를 확인한다.

### 최소 검증 기준

- 새 core 로직은 unit test 우선 작성
- API endpoint는 integration test 작성
- zip fixture 기반 업로드→분석→질문→리포트 흐름 테스트 작성
- LLM 호출이 필요한 테스트는 deterministic fixture를 사용한다.

## Deployment

### MVP 배포 방향

- Frontend: Streamlit 실행 환경
- Backend: Python ASGI 서버
- Database: SQLite3 file
- Vector DB: Qdrant local 또는 managed
- Artifact storage: local volume

### 운영보다 중요한 MVP 조건

- zip 업로드 자료가 분석되고 질문으로 이어지는지
- 단계형 인터뷰가 10분 내외로 진행되는지
- 답변 평가가 제출 자료 근거와 연결되는지
- 최종 리포트가 프로젝트 영역별로 설득력 있게 나오는지
- 새 환경에서 빠르게 실행할 수 있는지

## 선택하지 않은 대안

### Next.js frontend

선택하지 않는다.

- 현재 목표는 빠른 캡스톤 시연이다.
- Streamlit이 Python 기반 backend/core와 더 빠르게 결합된다.
- 정교한 WebRTC UX는 후순위다.

### PostgreSQL

MVP에서는 선택하지 않는다.

- 별도 DB 설치/컨테이너 운영이 필요하다.
- 단일 로컬 시연에는 SQLite3가 충분하다.
- 추후 운영화가 필요하면 repository boundary를 통해 전환한다.

### 기존 backend/frontend 확장

선택하지 않는다.

- 기존 도메인에는 강의실, 학생/교수자, 일반 시험 운영 등 불필요한 개념이 많다.
- `v2/`의 목표는 프로젝트 수행 진위 검증 하나다.
- 새 프로젝트가 더 빠르고 명확하다.

### Celery 기반 worker 선도입

MVP 첫 단계에서는 선택하지 않는다.

- 운영 복잡도가 늘어난다.
- capstone 시연 목적에서는 FastAPI BackgroundTasks로 충분히 시작할 수 있다.

### 인증 시스템 선도입

MVP에서는 선택하지 않는다.

- 학교 로그인, 역할 관리, 복잡한 권한 시스템은 제외 범위다.

## 권장 디렉터리 구조

```text
v2/
├── apps/
│   └── streamlit/               # Streamlit frontend
├── services/
│   └── api/                     # FastAPI backend + project evaluation core
│       ├── app/
│       │   ├── project_evaluations/
│       │   │   ├── domain/
│       │   │   ├── ingestion/
│       │   │   ├── rag/
│       │   │   ├── interview/
│       │   │   └── reports/
│       │   ├── database/
│       │   └── settings.py
│       ├── tests/
│       └── pyproject.toml
├── data/
│   ├── app.db                   # SQLite3 local database
│   └── artifacts/               # 제출 zip 및 추출 자료
├── cli/                         # 기존 MVP core 참조 소스
├── docs/
│   ├── project-evaluation-scope.md
│   └── tech-stack.md
└── scripts/
    └── reset-demo-data.sh
```

## 구현 순서

1. FastAPI + Streamlit + SQLite3 skeleton 작성
2. SQLite 저장 모델과 repository 작성
3. 기존 CLI core에서 Bloom, 루브릭, 질문, 리포트 모델 개념 이식
4. 단일 zip 업로드와 텍스트 추출 구현
5. Qdrant embedding 저장과 retrieval 구현
6. 프로젝트 context 생성과 질문 생성 구현
7. 답변 평가, 꼬리질문, 리포트 생성 구현
8. Streamlit 업로드/분석/인터뷰/리포트 화면 구현
9. 오디오 입력/STT/TTS를 단계형 인터뷰에 연결
10. 데모 zip으로 MVP golden path 검증

## 공식 문서 확인 사항

- FastAPI 문서 기준, Pydantic model은 request/response schema와 OpenAPI 문서 생성을 함께 지원한다.
- Streamlit 문서 기준, `st.file_uploader`는 단일/다중 파일 업로드를 지원하고, `st.session_state`는 form과 인터뷰 진행 상태 관리에 사용할 수 있다.
- Streamlit 문서 기준, `st.audio_input`은 브라우저 마이크 녹음 데이터를 받아 처리할 수 있다.
