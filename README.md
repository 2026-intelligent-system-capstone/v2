# 프로젝트 수행 진위 평가 서비스

지원자가 제출한 프로젝트 zip 파일을 분석하고, 실시간 음성 인터뷰로 수행 진위를 검증하는 시스템입니다.

## 기능 요약

- **zip 업로드**: PDF, PPTX, DOCX, README, 소스 코드가 포함된 단일 zip 파일 제출
- **자료 분석**: 기술 스택, 주요 기능, 아키텍처, 리스크 포인트 자동 추출
- **질문 생성**: Bloom's Taxonomy 기반 인터뷰 질문 자동 생성
- **실시간 음성 인터뷰**: OpenAI Realtime API를 이용한 양방향 음성 대화
- **리포트 생성**: 프로젝트 영역별 신뢰도, 루브릭 점수, 의심 지점 포함 상세 리포트

## 사전 요구사항

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) 패키지 매니저
- OpenAI API 키 (GPT-4o-mini, Realtime API 사용 권한)
- Docker (Qdrant 사용 시 선택사항)

## 빠른 시작

### 1. 의존성 설치

```bash
uv sync
```

### 2. 환경변수 설정

백엔드 실행을 위해 설정 파일이 필요합니다.

**Unix (macOS/Linux):**
```bash
cp .env.example .env
cp backend/.env.example backend/.env
```

**Windows (CMD):**
```cmd
copy .env.example .env
copy backend\.env.example backend\.env
```

`.env` 파일을 열어 `OPENAI_API_KEY`를 설정하세요.

`.env` 주요 항목:

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `OPENAI_API_KEY` | OpenAI API 키 | (필수) |
| `QDRANT_URL` | Qdrant 벡터 DB URL (선택) | `http://localhost:6333` |
| `APP_SQLITE_PATH` | SQLite DB 경로 | `data/app.db` |

### 3. 데이터 디렉터리 생성

백엔드에서 사용할 데이터 저장 폴더를 생성합니다.

**Unix (macOS/Linux):**
```bash
mkdir -p backend/data/artifacts
touch backend/data/artifacts/.gitkeep
```

**Windows (CMD):**
```cmd
if not exist "backend\data\artifacts" mkdir "backend\data\artifacts"
type NUL > backend\data\artifacts\.gitkeep
```

### 4. Qdrant 시작 (선택사항 — RAG 기능 활성화)

```bash
# Docker가 설치되어 있어야 합니다.
docker compose up -d qdrant
```

Qdrant 없이도 동작합니다. RAG 없이 rule-based 질문 생성으로 폴백합니다.

### 5. FastAPI 서버 시작

```bash
# 공통 (Backend 디렉토리에서 실행)
cd backend
uv run uvicorn app.main:app --reload
```

서버가 `http://localhost:8000`에서 시작됩니다.
API 문서: `http://localhost:8000/docs`

### 6. UI 시작

이 프로젝트는 두 가지 UI를 제공합니다.

#### Streamlit UI (학습용/관리자)
```bash
# 루트 디렉토리에서 실행
uv run streamlit run apps/streamlit/Home.py
```
브라우저에서 `http://localhost:8501`로 접속합니다.

#### Next.js UI (사용자용)
```bash
cd frontend
pnpm install
pnpm dev
```
브라우저에서 `http://localhost:3000`으로 접속합니다.

## 사용 흐름

```
1. 프로젝트명, 지원자명, 설명 입력
2. 프로젝트 자료 zip 파일 업로드
3. "context 생성 및 질문 만들기" 클릭 → 자료 분석 및 질문 생성
4. "실시간 음성 인터뷰 시작" 버튼 → 새 탭에서 음성 인터뷰 진행
5. 인터뷰 완료 후 "리포트 확인" 버튼 → 영역별 신뢰도 리포트 확인
```

## 테스트

**백엔드 테스트 실행:**
```bash
cd backend
uv run pytest tests/test_evaluation_api.py -v
```

## 프로젝트 구조

```
v2/
├── apps/
│   └── streamlit/          # Streamlit UI (Home.py, api_client.py)
├── backend/                # FastAPI 백엔드
│   ├── app/
│   │   ├── project_evaluations/
│   │   │   ├── analysis/       # context 추출, LLM 클라이언트
│   │   │   ├── domain/         # Pydantic 모델, DB Row 모델
│   │   │   ├── ingestion/      # zip 처리, 텍스트 추출
│   │   │   ├── interview/      # 질문 생성, 답변 평가
│   │   │   ├── persistence/    # SQLAlchemy repository
│   │   │   ├── rag/            # Qdrant embedder, retriever
│   │   │   ├── realtime/       # OpenAI Realtime API 프록시
│   │   │   └── reports/        # 최종 리포트 생성
│   │   ├── main.py
│   │   └── settings.py
│   ├── data/               # SQLite3 DB 및 업로드 artifacts
│   └── tests/
├── frontend/               # Next.js 프론트엔드
├── docs/                   # 문서 (scope, tech stack 등)
├── Makefile
└── pyproject.toml
```

## 최종 판정 기준

| 판정 | 기준 |
|------|------|
| 검증 통과 | 신뢰도 점수 >= 70 |
| 추가 확인 필요 | 신뢰도 점수 40 ~ 69 |
| 신뢰 낮음 | 신뢰도 점수 < 40 |
