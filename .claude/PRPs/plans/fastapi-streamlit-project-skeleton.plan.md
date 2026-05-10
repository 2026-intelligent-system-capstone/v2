# Plan: FastAPI + Streamlit Project Skeleton

## Summary

PRD Phase 1은 FastAPI backend, Streamlit frontend, SQLite3 local storage, Qdrant local baseline을 갖춘 실행 가능한 프로젝트 뼈대를 만드는 작업이다. 이 단계는 아직 프로젝트 평가 도메인 로직을 구현하지 않고, 이후 domain/persistence/ingestion/RAG/interview/report 기능이 들어갈 안정적인 디렉터리 구조, 설정, health check, 테스트, 로컬 실행 명령을 준비한다.

## User Story

As a 프로젝트 평가 서비스를 구현하는 개발자,
I want FastAPI + Streamlit + SQLite3 기반 skeleton을 빠르게 실행할 수 있기를,
so that 이후 zip 분석, 질문 생성, 인터뷰, 리포트 기능을 같은 구조 안에서 단계적으로 구현할 수 있다.

## Problem → Solution

현재 `v2/`에는 기존 CLI MVP와 문서만 있고, 새 Web 서비스 실행 구조가 없다. → `services/api`와 `apps/streamlit`을 만들고, 공통 Python/uv 의존성, FastAPI health endpoint, Streamlit 기본 화면, SQLite data path, Qdrant compose baseline, 테스트/실행 명령을 추가한다.

## Metadata

- **Complexity**: Medium
- **Source PRD**: `.claude/PRPs/prds/fastapi-streamlit-project-evaluation.prd.md`
- **PRD Phase**: Phase 1 — Project skeleton
- **Estimated Files**: 13-18

---

## UX Design

### Before

```text
┌─────────────────────────────┐
│ v2 root                     │
│  ├─ cli/                    │
│  │   └─ 기존 CLI MVP         │
│  ├─ docs/                   │
│  └─ CLAUDE.md               │
│                             │
│ FastAPI service 없음         │
│ Streamlit app 없음           │
│ SQLite data path 없음        │
└─────────────────────────────┘
```

### After

```text
┌─────────────────────────────┐
│ FastAPI API                 │
│  GET /health                │
│  app settings 로드           │
│  SQLite path 준비            │
└──────────────┬──────────────┘
               │ HTTP
               ▼
┌─────────────────────────────┐
│ Streamlit UI                │
│  서비스 제목                 │
│  API 상태 확인               │
│  zip 업로드 placeholder      │
│  Phase 1 안내                │
└─────────────────────────────┘
```

### Interaction Changes

| Touchpoint | Before | After | Notes |
|---|---|---|---|
| 개발 실행 | `cli/` 명령만 존재 | FastAPI와 Streamlit을 각각 실행 | 도메인 기능은 아직 없음 |
| 상태 확인 | Qdrant status Make target만 존재 | `GET /health` + Streamlit API status | Phase 1 smoke test 기준 |
| 저장소 | CLI는 Qdrant 중심 | SQLite3 파일 경로와 artifact 디렉터리 예약 | 실제 schema는 Phase 2 |
| UI | 없음 | Streamlit 시작 화면 | 업로드/인터뷰 기능은 placeholder |

---

## Mandatory Reading

Files that MUST be read before implementing:

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `.claude/PRPs/prds/fastapi-streamlit-project-evaluation.prd.md` | 156-173 | Phase 1 scope, success signal, dependencies |
| P0 | `docs/tech-stack.md` | 1-45 | 확정 기술 스택과 전체 아키텍처 |
| P0 | `docs/tech-stack.md` | 87-138 | FastAPI backend 역할과 BackgroundTasks 정책 |
| P0 | `docs/tech-stack.md` | 234-268 | SQLite3 persistence 정책과 data path 원칙 |
| P0 | `docs/tech-stack.md` | 269-292 | 로컬 실행 명령 방향 |
| P0 | `cli/config.py` | 1-16 | Pydantic Settings + `.env` 로딩 패턴 |
| P0 | `cli/pyproject.toml` | 1-29 | uv/PEP 621 dependency group 패턴 |
| P0 | `cli/tests/conftest.py` | 1-6 | 테스트 환경변수 주입과 import path 패턴 |
| P0 | `cli/models.py` | 1-25, 39-78, 111-134 | Pydantic/Enum/model_validator naming and validation pattern |
| P1 | `cli/docker-compose.yml` | 1-13 | Qdrant service compose baseline |
| P1 | `cli/Makefile` | 4-17 | Qdrant up/down/reset/status target pattern |
| P1 | `cli/cli_generate_exam.py` | 11-15, 103-109 | API exception → user-facing error message mapping pattern |
| P1 | `cli/tests/test_models.py` | 18-31, 60-80 | pytest helper and validation test style |
| P1 | `cli/tests/test_generate_exam_result_models.py` | 24-60 | monkeypatch fake graph pattern |
| P2 | `cli/.env.example` | 1-2 | env example style |
| P2 | `cli/.gitignore` | 232-236 | SQLite ignore precedent |
| P2 | `.claude/PRPs/plans/webui-exam-room-flow.plan.md` | 1-160 | Existing PRP plan style and fact block convention |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| FastAPI minimal app | Context7 `/websites/fastapi_tiangolo` | `app = FastAPI()` and `@app.get("/")` style is official minimal pattern. Use same shape for `/health`. |
| FastAPI testing | Context7 `/websites/fastapi_tiangolo` | `fastapi.testclient.TestClient` is the documented basic endpoint test pattern. |
| FastAPI file upload | Context7 `/websites/fastapi_tiangolo` | `UploadFile` supports multipart upload, but Phase 1 should not implement zip ingestion yet. |
| Streamlit file uploader | Context7 `/streamlit/docs` | `st.file_uploader("...", type=[...])` returns uploaded file object with `.name`, `.type`, `.size`, `.read()`/`.getvalue()`. |
| Streamlit session state | Context7 `/streamlit/docs` | `st.session_state` stores UI state across reruns; use it later for evaluation/session IDs. |
| Streamlit audio input | Context7 `/streamlit/docs` | `st.audio_input("...")` returns recorded audio data; Phase 1 may mention placeholder only. |
| Streamlit chat input | Context7 `/streamlit/docs` | `st.chat_input(..., accept_file=False, accept_audio=False, ...)` exists, but Phase 1 should not wire interview yet. |

---

## Patterns to Mirror

Code patterns discovered in the codebase. Follow these exactly where they still fit the new project.

### NAMING_CONVENTION
// SOURCE: `cli/models.py:6-25`, `cli/models.py:39-45`, `cli/models.py:111-126`
```python
class ExamType(str, Enum):
    QUIZ = "quiz"
    MIDTERM_FINAL = "midterm_final"
    MOCK = "mock"


class BloomRatio(BaseModel):
    remember: int = Field(0, ge=0, le=100, description="기억 단계 비율(%)")


class ExamConfig(BaseModel):
    subject: str = Field(description="과목(강의)명")
```

Use PascalCase for Pydantic classes, `str, Enum` for string enums, and snake_case for fields. New skeleton settings should use a similarly explicit Pydantic class name such as `ApiSettings` or `CommonSettings`.

### SETTINGS_PATTERN
// SOURCE: `cli/config.py:1-16`
```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class CommonSettings(BaseSettings):
    OPENAI_API_KEY: str
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION_NAME: str = "lecture_materials"
    TAVILY_API_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )


config = CommonSettings()  # type: ignore[call-arg]
```

Mirror `BaseSettings`, `.env`, `case_sensitive=True`, and `extra="ignore"`. Do not require `OPENAI_API_KEY` for Phase 1 health checks; make it optional or empty so skeleton tests pass without real secrets.

### VALIDATION_PATTERN
// SOURCE: `cli/models.py:128-134`, `cli/models.py:158-198`
```python
@model_validator(mode="after")
def validate_question_types(self):
    if not self.question_types:
        raise ValueError("허용할 문제 유형은 최소 1개 이상이어야 합니다.")
    if len(set(self.question_types)) != len(self.question_types):
        raise ValueError("허용할 문제 유형은 중복 없이 지정해야 합니다.")
    return self
```

When Phase 1 adds settings validation, prefer Pydantic validation errors over ad-hoc checks. Keep Korean user-facing messages where validation is product-facing.

### ERROR_HANDLING
// SOURCE: `cli/cli_generate_exam.py:11-15`, `cli/cli_generate_exam.py:103-109`
```python
_API_ERROR_MESSAGES = {
    RateLimitError: "OpenAI API 사용 한도를 초과했습니다. 크레딧을 확인해주세요: https://platform.openai.com/settings/organization/billing/overview",
    AuthenticationError: "OpenAI API 키가 유효하지 않습니다. .env 파일의 OPENAI_API_KEY를 확인해주세요.",
    APIConnectionError: "OpenAI API에 연결할 수 없습니다. 네트워크 상태를 확인해주세요.",
}

try:
    result = run_exam_generation(exam_config)
except tuple(_API_ERROR_MESSAGES.keys()) as e:
    msg = _API_ERROR_MESSAGES.get(type(e), f"OpenAI API 오류: {e}")
    print(f"\n[오류] {msg}", file=sys.stderr)
    raise SystemExit(1) from None
```

Phase 1 should avoid OpenAI calls, but future API errors should map external exceptions to Korean user-facing messages. For FastAPI skeleton health endpoint, return explicit status instead of swallowing errors.

### LOGGING_PATTERN
// SOURCE: `cli/cli_generate_exam.py:103-109`, repo scan by Explore agent
```python
print(f"\n[오류] {msg}", file=sys.stderr)
```

Existing CLI does not use structured logging. New FastAPI code should introduce `logging.getLogger(__name__)` only for server startup or unexpected API diagnostics if needed, and must avoid `print()` in new Python service code per project Python hook guidance.

### TEST_STRUCTURE
// SOURCE: `cli/tests/conftest.py:1-6`
```python
import os
import sys
from pathlib import Path

os.environ.setdefault("OPENAI_API_KEY", "test-key")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

For new service tests, set safe environment defaults before importing settings. Prefer explicit `tmp_path` or env override for SQLite path so tests never write to real `data/app.db`.

### TEST_HELPER_PATTERN
// SOURCE: `cli/tests/test_models.py:18-31`, `cli/tests/test_models.py:60-80`
```python
def build_question(**overrides):
    data = {
        "question_number": 1,
        "bloom_level": BloomLevel.UNDERSTAND,
        "question": "옵저버 패턴이 무엇인가요?",
    }
    data.update(overrides)
    return GeneratedQuestion(**data)


@pytest.mark.parametrize(
    "options,correct_answer",
    [
        ([], "A"),
        ([QuestionOption(label="A", text="옵저버")], None),
    ],
)
def test_multiple_choice_question_rejects_missing_required_fields(options, correct_answer):
    with pytest.raises(ValidationError):
        build_question(...)
```

Use small `build_*` helpers for repeated setup and `pytest.mark.parametrize` for edge cases.

### MONKEYPATCH_PATTERN
// SOURCE: `cli/tests/test_generate_exam_result_models.py:24-60`
```python
class FakeGraph:
    def invoke(self, initial_state):
        return fake_result

monkeypatch.setattr(generate_exam, "build_exam_graph", lambda: FakeGraph())
```

When testing Streamlit API client functions later, monkeypatch HTTP calls rather than hitting a live server. Phase 1 can avoid Streamlit runtime tests and focus on API TestClient tests.

### QDRANT_COMPOSE_PATTERN
// SOURCE: `cli/docker-compose.yml:1-13`
```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    container_name: llm-qdrant
    restart: unless-stopped
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_storage:/qdrant/storage

volumes:
  qdrant_storage:
```

Root compose should mirror this service but avoid the old `llm-qdrant` name if both CLI and new service may run together. Prefer `project-evaluation-qdrant`.

### MAKEFILE_PATTERN
// SOURCE: `cli/Makefile:4-17`
```makefile
.PHONY: qdrant-up qdrant-down qdrant-reset qdrant-status

qdrant-up:
	docker compose up -d

qdrant-down:
	docker compose down

qdrant-reset:
	docker compose down -v
	docker compose up -d

qdrant-status:
	@curl -s http://localhost:6333/collections | python3 -m json.tool
```

If adding a root Makefile, keep simple phony targets and `uv run ...` commands. Avoid copying education-domain targets (`generate-exam`, `take-exam`) into v2 root.

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `pyproject.toml` | CREATE | Root uv project/workspace for FastAPI, Streamlit, SQLite, tests, linting |
| `.env.example` | CREATE | Document local skeleton env vars without secrets |
| `.gitignore` | CREATE or UPDATE | Ignore `.env`, SQLite db/journal files, artifacts, caches |
| `services/api/app/__init__.py` | CREATE | Python package marker |
| `services/api/app/main.py` | CREATE | FastAPI app factory/root app and health route |
| `services/api/app/settings.py` | CREATE | Pydantic Settings for API, SQLite path, Qdrant URL, artifact directory |
| `services/api/app/database.py` | CREATE | SQLite path initialization and future engine boundary |
| `services/api/tests/conftest.py` | CREATE | Test env defaults and import path setup |
| `services/api/tests/test_health.py` | CREATE | FastAPI TestClient health endpoint test |
| `apps/streamlit/Home.py` | CREATE | Minimal Streamlit app with API status and upload placeholder |
| `apps/streamlit/api_client.py` | CREATE | Tiny HTTP client for `GET /health` used by UI |
| `apps/streamlit/__init__.py` | CREATE | Python package marker for tests/future imports |
| `docker-compose.yml` | CREATE | Qdrant local baseline at root |
| `Makefile` | CREATE | Local run/test/qdrant/demo reset commands |
| `data/.gitkeep` | CREATE | Reserve local data directory without committing DB/artifacts |
| `data/artifacts/.gitkeep` | CREATE | Reserve artifact directory |
| `scripts/reset-demo-data.sh` | CREATE | Remove local SQLite DB and uploaded artifacts for demo reset |
| `.claude/PRPs/prds/fastapi-streamlit-project-evaluation.prd.md` | UPDATE | Mark Phase 1 in-progress and link this plan |

## NOT Building

- Domain models for `ProjectEvaluation`, `ProjectArtifact`, questions, sessions, scores, reports
- SQLite schema tables beyond path initialization placeholder
- Zip upload/ingestion endpoint
- Qdrant collection creation or embedding writes
- LLM/OpenAI calls
- STT/TTS integration
- Streamlit real upload flow beyond placeholder
- Authentication or role management
- PDF export
- GitHub URL ingestion

---

## Step-by-Step Tasks

### Task 1: Create root Python project metadata
- **ACTION**: Create root `pyproject.toml`.
- **IMPLEMENT**: Define a uv-managed Python project for the new app, with Python `>=3.13`; dependencies should include `fastapi`, `uvicorn[standard]`, `streamlit`, `requests` or `httpx`, `pydantic`, `pydantic-settings`, `sqlalchemy`, `qdrant-client`, `python-multipart`; dev dependencies include `pytest`, `ruff`.
- **MIRROR**: `cli/pyproject.toml:1-29` PEP 621 + dependency-groups style.
- **IMPORTS**: N/A.
- **GOTCHA**: Do not modify `cli/pyproject.toml`; the new root project is separate from the existing CLI subproject.
- **VALIDATE**: `uv sync` from `v2/` root should create/update the root environment without needing real OpenAI credentials.

### Task 2: Add local environment and ignore policy
- **ACTION**: Create `.env.example` and root `.gitignore` if missing.
- **IMPLEMENT**: `.env.example` should include synthetic placeholders: `OPENAI_API_KEY=`, `OPENAI_EMBEDDING_MODEL=text-embedding-3-small`, `QDRANT_URL=http://localhost:6333`, `QDRANT_COLLECTION_NAME=project_evaluation_chunks`, `APP_SQLITE_PATH=data/app.db`, `APP_ARTIFACT_DIR=data/artifacts`, `API_BASE_URL=http://localhost:8000`. `.gitignore` must ignore `.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `data/*.db`, `data/*.db-journal`, and `data/artifacts/*` while keeping `.gitkeep` files.
- **MIRROR**: `cli/.env.example:1-2`, `cli/.gitignore:232-236`.
- **IMPORTS**: N/A.
- **GOTCHA**: Never write real API keys; use blank or placeholder values only.
- **VALIDATE**: `test -f .env.example && test -f .gitignore`.

### Task 3: Create FastAPI settings and data path boundary
- **ACTION**: Create `services/api/app/settings.py` and `services/api/app/database.py`.
- **IMPLEMENT**: `settings.py` should define `ApiSettings(BaseSettings)` with env fields from `.env.example`, default SQLite path `data/app.db`, default artifact dir `data/artifacts`, default Qdrant collection `project_evaluation_chunks`, and `SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore")`. `database.py` should expose `ensure_data_paths(settings: ApiSettings) -> None` that creates parent directories for SQLite file and artifact dir. Keep it small; no ORM tables yet.
- **MIRROR**: `cli/config.py:1-16`.
- **IMPORTS**: `Path` from `pathlib`, `BaseSettings`, `SettingsConfigDict`.
- **GOTCHA**: `OPENAI_API_KEY` should not be required for skeleton import; use `str = ""` so health tests pass.
- **VALIDATE**: Import `from services.api.app.settings import ApiSettings` in a Python shell/test without `.env`.

### Task 4: Create FastAPI app and health endpoint
- **ACTION**: Create `services/api/app/main.py`.
- **IMPLEMENT**: Define `create_app() -> FastAPI`, instantiate `app = create_app()`, call `ensure_data_paths(settings)` during app creation, and expose `GET /health` returning a Pydantic-compatible dict such as `{ "status": "ok", "service": "project-evaluation-api", "storage": { "sqlite_path": "data/app.db" } }`. Keep endpoint simple and side-effect limited to data path creation.
- **MIRROR**: FastAPI official minimal app docs; codebase settings pattern from `cli/config.py:1-16`.
- **IMPORTS**: `FastAPI`, local `ApiSettings`, `ensure_data_paths`.
- **GOTCHA**: Avoid doing Qdrant/OpenAI connectivity checks in `/health`; Phase 1 should be reliable without external services.
- **VALIDATE**: `uv run uvicorn services.api.app.main:app --reload` starts and `GET /health` returns 200.

### Task 5: Add FastAPI tests
- **ACTION**: Create `services/api/tests/conftest.py` and `services/api/tests/test_health.py`.
- **IMPLEMENT**: `conftest.py` should set safe defaults for `OPENAI_API_KEY`, `APP_SQLITE_PATH`, and `APP_ARTIFACT_DIR` before importing app modules; it may insert repo root into `sys.path` if needed. `test_health.py` should use `fastapi.testclient.TestClient` against `app` and assert status 200, `status == "ok"`, and service name.
- **MIRROR**: `cli/tests/conftest.py:1-6`, FastAPI TestClient docs, `cli/tests/test_models.py:18-31` simple helper style if helper needed.
- **IMPORTS**: `os`, `sys`, `Path`, `TestClient`, `app`.
- **GOTCHA**: Ensure test SQLite path uses a temp/test path, not real `data/app.db`; if module-level settings are instantiated, env must be set before app import.
- **VALIDATE**: `uv run pytest services/api/tests` passes.

### Task 6: Create Streamlit API client
- **ACTION**: Create `apps/streamlit/api_client.py`.
- **IMPLEMENT**: Define `get_api_base_url() -> str` reading `API_BASE_URL` from env with default `http://localhost:8000`, and `get_health() -> dict[str, object]` using `requests.get(..., timeout=5)` or `httpx.get(..., timeout=5.0)`. Return parsed JSON on success and raise a clear exception on failure.
- **MIRROR**: External API error mapping concept from `cli/cli_generate_exam.py:11-15`, but use exceptions rather than `print()`.
- **IMPORTS**: `os`, `requests` or `httpx`.
- **GOTCHA**: Streamlit should call FastAPI, not import FastAPI internals directly. Avoid circular imports.
- **VALIDATE**: Unit-test later by monkeypatching HTTP calls; Phase 1 manual validation can start FastAPI and display status.

### Task 7: Create minimal Streamlit app
- **ACTION**: Create `apps/streamlit/Home.py`.
- **IMPLEMENT**: Render service title, short description, API status section using `get_health()`, zip upload placeholder with `st.file_uploader("프로젝트 자료 zip 업로드", type=["zip"])`, and informational message that ingestion/interview/report are planned in later phases. Optionally show uploaded file name/size only; do not send it to backend yet.
- **MIRROR**: Streamlit docs for `st.file_uploader`, `st.session_state` if storing API status or uploaded filename.
- **IMPORTS**: `streamlit as st`, local `get_health`.
- **GOTCHA**: The file is named `Home.py` per docs plan, but importing sibling `api_client.py` may require running from repo root or adding package-safe import. Prefer `from apps.streamlit.api_client import get_health` if package structure supports it.
- **VALIDATE**: `uv run streamlit run apps/streamlit/Home.py` opens a page and shows API unavailable gracefully if FastAPI is not running, or OK if it is.

### Task 8: Add Qdrant compose baseline
- **ACTION**: Create root `docker-compose.yml`.
- **IMPLEMENT**: Add Qdrant service mirroring CLI compose, with container name `project-evaluation-qdrant`, ports `6333:6333` and `6334:6334`, named volume `project_evaluation_qdrant_storage`.
- **MIRROR**: `cli/docker-compose.yml:1-13`.
- **IMPORTS**: N/A.
- **GOTCHA**: Avoid reusing `llm-qdrant` container name from CLI to prevent collision.
- **VALIDATE**: `docker compose config` succeeds; `docker compose up -d qdrant` starts Qdrant if Docker is available.

### Task 9: Add root Makefile and demo reset script
- **ACTION**: Create `Makefile` and `scripts/reset-demo-data.sh`.
- **IMPLEMENT**: Makefile targets: `api`, `streamlit`, `test`, `lint`, `format`, `qdrant-up`, `qdrant-down`, `qdrant-reset`, `qdrant-status`, `reset-demo-data`. Use `uv run ...` commands from docs. Reset script removes `data/app.db`, `data/app.db-journal`, and artifact children while preserving `.gitkeep`.
- **MIRROR**: `cli/Makefile:4-17` target style.
- **IMPORTS**: N/A.
- **GOTCHA**: Deleting data is destructive; keep reset scoped strictly to local demo paths and do not run it unless explicitly validating reset behavior.
- **VALIDATE**: `make test` runs pytest; `make lint` runs ruff; `make qdrant-status` returns JSON when Qdrant is up.

### Task 10: Reserve data directories
- **ACTION**: Create `data/.gitkeep` and `data/artifacts/.gitkeep`.
- **IMPLEMENT**: Empty placeholder files only.
- **MIRROR**: Tech stack data path policy `docs/tech-stack.md:254-260`.
- **IMPORTS**: N/A.
- **GOTCHA**: `.gitignore` must not ignore `.gitkeep` files.
- **VALIDATE**: `test -f data/.gitkeep && test -f data/artifacts/.gitkeep`.

### Task 11: Update PRD phase status
- **ACTION**: Update PRD Implementation Phase row for Phase 1.
- **IMPLEMENT**: Change status from `pending` to `in-progress` and PRP Plan from `-` to `.claude/PRPs/plans/fastapi-streamlit-project-skeleton.plan.md`.
- **MIRROR**: PRP skill instruction for PRD update.
- **IMPORTS**: N/A.
- **GOTCHA**: Do not mark later phases in-progress.
- **VALIDATE**: PRD table shows only Phase 1 as `in-progress`.

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| API health endpoint | `GET /health` | 200 and `status: ok` | No external Qdrant/OpenAI running |
| Settings defaults | no `.env` | default SQLite/artifact/Qdrant values load | missing `OPENAI_API_KEY` |
| Data path creation | temp SQLite path and artifact dir | parent dirs created | nested path does not exist |
| Streamlit API client success | monkeypatched 200 response | parsed health dict | later phase optional |
| Streamlit API client failure | monkeypatched timeout/error | clear exception or graceful UI message | API unavailable |

### Edge Cases Checklist

- [ ] Missing `.env`
- [ ] Empty `OPENAI_API_KEY`
- [ ] SQLite parent directory missing
- [ ] Artifact directory missing
- [ ] FastAPI running while Qdrant is down
- [ ] Streamlit running while FastAPI is down
- [ ] Docker unavailable
- [ ] Reset script does not delete outside `data/`

---

## Validation Commands

### Static Analysis
```bash
uv run ruff check .
```
EXPECT: Zero lint errors

### Formatting
```bash
uv run ruff format .
```
EXPECT: Files formatted

### Unit Tests
```bash
uv run pytest services/api/tests
```
EXPECT: FastAPI skeleton tests pass

### Full Test Suite
```bash
uv run pytest
```
EXPECT: New root tests pass. Existing `cli/` tests may need separate execution from `cli/` if root package layout excludes them.

### Database Validation
```bash
uv run python - <<'PY'
from services.api.app.settings import ApiSettings
from services.api.app.database import ensure_data_paths
settings = ApiSettings(APP_SQLITE_PATH='data/app.db', APP_ARTIFACT_DIR='data/artifacts')
ensure_data_paths(settings)
print(settings.APP_SQLITE_PATH)
PY
```
EXPECT: `data/` and `data/artifacts/` exist; no real schema required in Phase 1

### Qdrant Validation
```bash
docker compose config
docker compose up -d qdrant
curl -s http://localhost:6333/collections | python3 -m json.tool
```
EXPECT: Docker compose is valid and Qdrant responds when Docker is available

### Browser Validation
```bash
uv run uvicorn services.api.app.main:app --reload
uv run streamlit run apps/streamlit/Home.py
```
EXPECT: Streamlit page loads; API status shows OK when FastAPI is running; upload widget accepts `.zip` selection but does not process it yet

### Manual Validation
- [ ] Start FastAPI and open `/health` in browser or curl
- [ ] Start Streamlit and confirm app title appears
- [ ] Confirm API status area shows healthy response
- [ ] Stop FastAPI and confirm Streamlit shows a graceful unavailable message
- [ ] Select a `.zip` file and confirm only filename/size placeholder appears
- [ ] Confirm no actual ingestion or LLM call is attempted

---

## Acceptance Criteria

- [ ] `uv sync` succeeds from `v2/` root
- [ ] FastAPI app imports and serves `GET /health`
- [ ] Streamlit app starts and renders the skeleton UI
- [ ] SQLite data path and artifact directory are defined and created safely
- [ ] Qdrant compose baseline exists at root
- [ ] `uv run pytest services/api/tests` passes
- [ ] `uv run ruff check .` passes or documented lint issues are fixed
- [ ] PRD Phase 1 is marked `in-progress` and links this plan

## Completion Checklist

- [ ] Code follows discovered Python/Pydantic naming patterns
- [ ] Settings follow `.env`/Pydantic Settings pattern
- [ ] Error handling avoids silent failures and avoids `print()` in new service code
- [ ] Tests follow pytest/TestClient patterns
- [ ] No hardcoded secrets
- [ ] No domain scope additions beyond skeleton
- [ ] Streamlit remains a UI/client layer only
- [ ] SQLite path is configurable via env
- [ ] Self-contained — no questions needed during implementation

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Root uv project conflicts with `cli/` subproject | Medium | Medium | Keep new root project separate; do not edit `cli/pyproject.toml`; document separate command contexts |
| Settings instantiated before test env override | Medium | Medium | Set env in `services/api/tests/conftest.py` before importing app |
| Streamlit imports fail due package path | Medium | Low | Use package-safe imports and run from repo root |
| Qdrant container name conflicts with CLI compose | Low | Medium | Use `project-evaluation-qdrant`, not `llm-qdrant` |
| Reset script deletes unintended files | Low | High | Scope script to `data/app.db`, `data/app.db-journal`, and `data/artifacts/*` only |
| Skeleton grows into domain implementation | Medium | Medium | Keep Phase 1 to health/status/placeholders; defer domain tables and upload processing to Phase 2/3 |

## Notes

- Phase 1 intentionally avoids actual project evaluation tables. SQLite schema belongs to Phase 2.
- Phase 1 intentionally avoids zip ingestion. Upload processing belongs to Phase 3.
- Phase 1 intentionally avoids LLM, OpenAI, STT/TTS calls so local smoke tests work without paid API calls.
- The current codebase has no established FastAPI skeleton inside `v2/`; the plan borrows CLI Python conventions and official FastAPI/Streamlit docs.
- Python project rules require type annotations on all function signatures and ruff formatting/linting.
