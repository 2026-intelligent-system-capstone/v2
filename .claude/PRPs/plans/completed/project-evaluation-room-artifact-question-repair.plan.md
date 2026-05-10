# Plan: Project Evaluation Room, Artifact, and Question Repair

## Summary
현재 v2 MVP는 FastAPI + Streamlit 기반 golden path는 있으나, 최신 제품 요구와 실제 구현 사이에 세 가지 큰 결함이 있다. 업로드 결과가 `ignored`와 실제 실패를 합쳐 “제외/실패”로 표시되고, 질문 생성은 자료 기반 LLM 실패 시 고정 템플릿으로 떨어지며, 교수자 방 생성/학생 응시자 입장/관리자 비밀번호 정책이 구현되어 있지 않다. 이 계획은 테스트 작성보다 기능 완성을 우선해, 기존 FastAPI service/repository 패턴과 Streamlit 단일 파일 UI 패턴을 유지하면서 방 정책, 업로드 집계, 자료 기반 fallback 질문, Realtime 세션 연결을 한 번에 보정한다.

## User Story
As a 교수자,
I want 방(시험)을 이름/비밀번호/관리자 비밀번호로 만들고 프로젝트 zip을 업로드해 자료 기반 질문을 생성하기를,
so that 학생이 실제로 프로젝트를 수행했는지 빠르게 검증할 수 있다.

As a 학생/인터뷰 대상자,
I want 방 URL 또는 방 ID와 비밀번호로 입장해 실시간 음성 인터뷰를 보기를,
so that 별도 계정 없이 내가 수행한 프로젝트를 음성으로 설명할 수 있다.

## Problem → Solution
현재 단일 업로드 화면은 교수자와 학생 역할을 섞고, artifact skip reason을 숨기며, LLM 실패 시 `CLAUDE 영역에서...` 같은 고정 질문을 생성한다. → `ProjectEvaluation`을 방/시험 단위로 확장하고, `InterviewSession`을 학생 응시 세션으로 분리하며, 업로드 reason 집계와 source-ref 기반 질문 fallback을 추가하고, Streamlit을 교수자/학생 모드로 나눈다.

## Metadata
- **Complexity**: Large
- **Source PRD**: `.claude/PRPs/prds/fastapi-streamlit-project-evaluation.prd.md`
- **PRD Phase**: Phase 8 — Room flow, artifact transparency, and grounded questions
- **Estimated Files**: 11-14

---

## UX Design

### Before
```text
┌─────────────────────────────────────────────┐
│ Streamlit 단일 흐름                         │
│ 프로젝트명                                  │
│ 지원자/팀명                                 │
│ 설명                                        │
│ zip 업로드                                  │
│                                             │
│ 분석 대상: 28                               │
│ 제외/실패: 208                              │
│                                             │
│ 질문 미리보기                               │
│ Q1. CLAUDE 영역에서 핵심 흐름이...          │
│                                             │
│ [실시간 음성 인터뷰 시작]                   │
└─────────────────────────────────────────────┘
```

### After
```text
┌─────────────────────────────────────────────┐
│ 시작 화면                                   │
│ [교수자: 방 만들기/관리] [학생: 방 입장]    │
└──────────────────────┬──────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        ▼                             ▼
┌───────────────────────┐     ┌───────────────────────┐
│ 교수자 방 생성         │     │ 학생 방 입장           │
│ 방/시험 이름           │     │ 방 ID                  │
│ 프로젝트 이름          │     │ 이름/팀명              │
│ 방 비밀번호            │     │ 방 비밀번호            │
│ 관리자 비밀번호        │     │ [입장]                 │
│ zip 업로드             │     └───────────┬───────────┘
└───────────┬───────────┘                 ▼
            ▼                 ┌────────────────────────┐
┌────────────────────────┐    │ 실시간 음성 인터뷰      │
│ 교수자 관리 화면        │    │ 마이크 권한은 기존 유지 │
│ 추출 성공/무시/빈텍스트 │    │ 종료 후 리포트 생성     │
│ 용량초과/실패 분리 표시 │    └────────────────────────┘
│ source 기반 질문 표시   │
│ session별 리포트 확인   │
└────────────────────────┘
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| 평가 생성 | 프로젝트명/지원자명/설명 | 방 이름, 프로젝트명, 방 비밀번호, 관리자 비밀번호, 설명 | `candidate_name`은 유지하되 학생 session으로 이동 |
| 업로드 결과 | 분석 대상 / 제외·실패 | 추출 성공 / 무시됨 / 텍스트 없음 / 용량 초과 / 처리 제한 / 실패 | 실제 실패와 정상 ignored 분리 |
| 질문 생성 | LLM 실패 시 고정 템플릿 | LLM 실패 시에도 source path/snippet 기반 질문 | `CLAUDE 영역` generic 질문 금지 |
| 학생 응시 | 교수자 흐름에서 session 생성 | 방 ID + 방 비밀번호 + 이름으로 session 생성 | 로그인 없음 |
| 관리자 확인 | 없음 | 관리자 비밀번호 검증 후 업로드/분석/리포트 | 과한 인증 시스템은 만들지 않음 |
| Realtime | 평가 session 직접 시작 | join으로 만든 학생 session의 realtime URL 사용 | 마이크 권한 로직은 유지 |

---

## Mandatory Reading

Files that MUST be read before implementing:

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `services/api/app/project_evaluations/domain/models.py` | 8-29, 81-117, 164-177 | API enum/schema와 upload result/session request 확장 지점 |
| P0 | `services/api/app/project_evaluations/persistence/models.py` | 15-47, 110-126 | SQLite table 확장 대상: evaluation room fields, session participant |
| P0 | `services/api/app/project_evaluations/persistence/repository.py` | 73-131, 270-326, 520-595 | create/read 변환 패턴, question/session 저장 패턴 |
| P0 | `services/api/app/project_evaluations/service.py` | 73-117, 199-237, 345-365 | upload/create/question/session orchestration 확장 지점 |
| P0 | `services/api/app/project_evaluations/ingestion/zip_handler.py` | 57-91, 99-157, 168-175 | reason metadata 생성 위치와 upload count 계산 근거 |
| P0 | `services/api/app/project_evaluations/interview/question_generator.py` | 24-44, 55-71, 115-137 | generic fallback 질문 제거 대상 |
| P0 | `apps/streamlit/Home.py` | 23-33, 74-123, 149-189 | Streamlit state와 현재 단일 흐름 분리 대상 |
| P0 | `apps/streamlit/api_client.py` | 15-44, 62-84, 111-138 | API wrapper 패턴과 신규 endpoint 추가 위치 |
| P1 | `services/api/app/project_evaluations/router.py` | 42-64, 91-114, 153-167 | FastAPI endpoint shape와 response_model 패턴 |
| P1 | `services/api/app/project_evaluations/router_realtime.py` | 123-253 | 기존 브라우저 realtime URL/session 사용 방식 |
| P1 | `services/api/app/project_evaluations/realtime/proxy.py` | 19-35, 38-60, 97-117 | realtime 질문 instruction과 bulk completion 흐름 |
| P1 | `services/api/app/project_evaluations/analysis/context_builder.py` | 208-247 | 현재 project area가 top-level path 중심으로 뭉치는 원인 |
| P1 | `services/api/app/project_evaluations/analysis/prompts.py` | 89-116 | LLM 질문 생성 프롬프트가 요구하는 source-grounded 질문 원칙 |
| P2 | `services/api/tests/test_evaluation_api.py` | 49-93, 158-205 | 기존 pytest fixture/API golden path. 이번 작업은 기능 우선이라 회귀 확인용 |
| P2 | `pyproject.toml` | 6-28 | 의존성 추가 없이 구현해야 함 |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| Streamlit forms/session state | Context7 `/streamlit/docs` | `st.form`은 submit 시점에 위젯 값을 batch 처리하고 `st.session_state`로 UI 단계 상태를 보관한다. 현재 `Home.py` 패턴과 일치한다. |
| FastAPI request/response bodies | Context7 `/fastapi/fastapi/0.128.0` | Pydantic model을 request body로 받고 `response_model`로 list/dict schema를 자동 검증한다. 기존 `router.py` 패턴 유지. |
| FastAPI UploadFile | Context7 `/fastapi/fastapi/0.128.0` | `UploadFile` + `File(...)`로 multipart 업로드를 받는다. 기존 zip upload endpoint 유지. |
| SQLAlchemy 2 ORM | Context7 `/websites/sqlalchemy_en_20_orm` | `Mapped[...]` + `mapped_column()` declarative style과 `session.add/commit/refresh` 패턴이 현재 repository와 동일하다. |

---

## Patterns to Mirror

Code patterns discovered in the codebase. Follow these exactly.

### NAMING_CONVENTION
// SOURCE: `services/api/app/project_evaluations/domain/models.py:81-117`
```python
class ProjectEvaluationCreate(BaseModel):
    project_name: str = Field(min_length=1, max_length=200)
    candidate_name: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=2000)


class ProjectEvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_name: str
    candidate_name: str
    description: str
    status: EvaluationStatus
    created_at: datetime
    updated_at: datetime
```
Use `ThingCreate`, `ThingRead`, `ThingRequest` style Pydantic DTOs in `domain/models.py`. Keep Korean user-facing validation messages in service/router, not in field names.

### ERROR_HANDLING
// SOURCE: `services/api/app/project_evaluations/service.py:199-205`
```python
if self.repository.has_sessions(evaluation_id):
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="인터뷰가 시작된 평가는 질문을 다시 생성할 수 없습니다.",
    )
```
Use `HTTPException(status_code=..., detail="한국어 메시지")` inside service methods. Do not introduce a new exception hierarchy for this capstone MVP.

### LOGGING_PATTERN
// SOURCE: `services/api/app/project_evaluations/realtime/proxy.py:89-95`
```python
except Exception as exc:
    logger.error("Realtime proxy error: %s", exc)
    try:
        await browser_ws.send_json({"type": "error", "message": str(exc)})
    except Exception:
        pass
    return
```
Existing logging is module-level `logger = logging.getLogger(__name__)`, with `logger.error`/`logger.warning` only around realtime failures. For upload/question LLM fallback, prefer surfacing metadata/UI state rather than adding noisy logs everywhere.

### REPOSITORY_PATTERN
// SOURCE: `services/api/app/project_evaluations/persistence/repository.py:270-298`
```python
def save_questions(
    self, evaluation_id: str, questions: list[dict[str, Any]]
) -> list[InterviewQuestionRead]:
    self.session.execute(
        delete(InterviewQuestionRow).where(
            InterviewQuestionRow.evaluation_id == evaluation_id
        )
    )
    rows = []
    for index, question in enumerate(questions):
        row = InterviewQuestionRow(
            id=new_id(),
            evaluation_id=evaluation_id,
            project_area_id=question.get("project_area_id"),
            question=str(question["question"]),
            intent=str(question.get("intent", "")),
            bloom_level=str(question["bloom_level"]),
            difficulty=str(question.get("difficulty", Difficulty.MEDIUM.value)),
            rubric_criteria_json=to_json(question.get("rubric_criteria", [])),
            source_refs_json=to_json(question.get("source_refs", [])),
            expected_signal=str(question.get("expected_signal", "")),
            order_index=index,
        )
        self.session.add(row)
        rows.append(row)
    self.session.commit()
    for row in rows:
        self.session.refresh(row)
    return [self.to_question_read(row) for row in rows]
```
Use repository methods for DB changes; service orchestrates. JSON payload fields stay as `*_json` text columns with `to_json/from_json` helpers.

### SERVICE_PATTERN
// SOURCE: `services/api/app/project_evaluations/service.py:87-117`
```python
async def upload_zip(
    self, evaluation_id: str, upload: UploadFile
) -> ArtifactUploadResult:
    self.get_evaluation(evaluation_id)
    if self.repository.has_artifacts(evaluation_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 업로드된 자료가 있는 평가는 다시 업로드할 수 없습니다.",
        )
    extracted = await extract_zip_artifacts(evaluation_id, upload, self.settings)
    artifacts = [
        self.repository.create_artifact(...)
        for item in extracted
    ]
    self.repository.update_evaluation_status(
        evaluation_id, EvaluationStatus.UPLOADED
    )
    accepted_count = sum(1 for item in artifacts if item.status.value == "extracted")
    return ArtifactUploadResult(...)
```
Keep orchestration in `ProjectEvaluationService`; do not move business logic into Streamlit.

### ROUTER_PATTERN
// SOURCE: `services/api/app/project_evaluations/router.py:42-64`
```python
@router.post("", response_model=ProjectEvaluationRead)
def create_evaluation(
    payload: ProjectEvaluationCreate,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
) -> ProjectEvaluationRead:
    return service.create_evaluation(payload)
```
Add endpoints by delegating directly to service methods. Use `Annotated[ProjectEvaluationService, Depends(get_service)]` consistently.

### STREAMLIT_STATE_PATTERN
// SOURCE: `apps/streamlit/Home.py:23-35`
```python
def init_state() -> None:
    defaults = {
        "step": "upload",
        "evaluation": None,
        "context": None,
        "questions": [],
        "session": None,
        "turns": [],
        "report": None,
        "current_question_index": 0,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)
```
Extend `st.session_state` defaults for `mode`, `admin_verified`, `joined_session`, and `room_lookup`; keep values JSON-like.

### TEST_STRUCTURE
// SOURCE: `services/api/tests/test_evaluation_api.py:49-73`
```python
@pytest.fixture()
def evaluation_id() -> str:
    resp = client.post(
        "/api/project-evaluations",
        json={
            "project_name": "테스트 프로젝트",
            "candidate_name": "테스트 지원자",
            "description": "FastAPI 기반 REST API",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]
```
User explicitly prioritizes functionality over new tests. Use existing tests only as regression/smoke validation unless a tiny assertion update is required because response schema changed.

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `services/api/app/project_evaluations/domain/models.py` | UPDATE | Add room/admin/join request/response fields and upload reason counts. |
| `services/api/app/project_evaluations/persistence/models.py` | UPDATE | Add room fields to `ProjectEvaluationRow`; add `participant_name` to `InterviewSessionRow`. |
| `services/api/app/project_evaluations/persistence/repository.py` | UPDATE | Persist/verify room/admin password hashes, create named sessions, convert new fields. |
| `services/api/app/project_evaluations/service.py` | UPDATE | Add room creation/join/admin verification and upload reason aggregation; keep existing orchestration. |
| `services/api/app/project_evaluations/router.py` | UPDATE | Add admin verify and join endpoints; keep existing REST routes. |
| `services/api/app/project_evaluations/ingestion/zip_handler.py` | UPDATE | Preserve source type for skipped large/empty files; keep ignored reason metadata. |
| `services/api/app/project_evaluations/analysis/context_builder.py` | UPDATE | Improve area inference to avoid `CLAUDE`/top-level generic areas dominating. |
| `services/api/app/project_evaluations/interview/question_generator.py` | UPDATE | Replace generic fallback with source-ref/snippet grounded fallback questions. |
| `apps/streamlit/api_client.py` | UPDATE | Add create room/admin verify/join wrappers and consume upload reason counts. |
| `apps/streamlit/Home.py` | UPDATE | Split professor/admin and student/join UI flows; show artifact reason breakdown. |
| `services/api/tests/test_evaluation_api.py` | UPDATE MINIMALLY | Only update payload/schema assumptions if existing tests break. Do not expand test suite. |
| `.env.example` / `README.md` | UPDATE IF NEEDED | Only if new env or run instructions are required; likely not needed. |
| `.claude/PRPs/prds/fastapi-streamlit-project-evaluation.prd.md` | UPDATE | Add Phase 8 status/reference. |

## NOT Building

- Full login/account system.
- School LMS integration.
- Role-based auth middleware.
- Multi-professor dashboards.
- PDF export.
- GitHub URL ingestion.
- New frontend framework.
- New database migration framework.
- Broad new test suite; feature smoke validation is the priority.
- Rewriting working microphone permission flow.

---

## Step-by-Step Tasks

### Task 1: Extend API schemas for room policy and upload reason counts
- **ACTION**: Update `domain/models.py`.
- **IMPLEMENT**:
  - Add fields to `ProjectEvaluationCreate`: `room_name`, `room_password`, `admin_password`; keep `candidate_name` optional for backward compatibility.
  - Add fields to `ProjectEvaluationRead`: `room_name`.
  - Add `ArtifactUploadResult.reason_counts: dict[str, int]` and optional explicit counts if useful: `ignored_count`, `empty_text_count`, `file_too_large_count`, `failed_count`, `processed_file_limit_count`.
  - Add `AdminVerifyRequest`, `AdminVerifyRead`, `JoinEvaluationRequest`, `JoinEvaluationRead` or similar Pydantic models.
  - Add `participant_name` to `InterviewSessionRead`.
- **MIRROR**: `ProjectEvaluationCreate/Read` style from `domain/models.py:81-117`.
- **IMPORTS**: Existing `BaseModel`, `ConfigDict`, `Field`, `datetime`; no new dependency.
- **GOTCHA**: Do not expose password hash in any `Read` schema. Do not require `candidate_name` for professor-created room.
- **VALIDATE**: `python -m compileall services/api/app/project_evaluations/domain/models.py` or full `uv run pytest` later.

### Task 2: Add SQLite fields without introducing Alembic
- **ACTION**: Update `persistence/models.py`.
- **IMPLEMENT**:
  - `ProjectEvaluationRow.room_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")`.
  - `ProjectEvaluationRow.room_password_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")`.
  - `ProjectEvaluationRow.admin_password_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")`.
  - `InterviewSessionRow.participant_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")`.
- **MIRROR**: SQLAlchemy 2 `Mapped`/`mapped_column` style from `persistence/models.py:15-47` and Context7 SQLAlchemy docs.
- **IMPORTS**: Existing `String`, `Text` already imported.
- **GOTCHA**: `Base.metadata.create_all()` will not add columns to an existing SQLite DB. For local MVP, either document/reset demo DB or add a tiny `ensure_schema_columns(engine)` in `database.py` using SQLite `ALTER TABLE ADD COLUMN` for these four columns. Prefer tiny schema patch because the user has live `data/app.db`.
- **VALIDATE**: Start API once and inspect `PRAGMA table_info(project_evaluations)` / `interview_sessions` manually if needed.

### Task 3: Implement lightweight password hashing helpers inside service or repository
- **ACTION**: Add local helper functions, preferably in `service.py` or a small internal module only if necessary.
- **IMPLEMENT**:
  - Use stdlib only: `hashlib.pbkdf2_hmac`, `secrets.token_hex`, `hmac.compare_digest`.
  - Store format like `pbkdf2_sha256$iterations$salt$hash`.
  - Implement `_hash_password(password: str) -> str` and `_verify_password(password: str, stored: str) -> bool`.
- **MIRROR**: Keep no new dependencies per `pyproject.toml:6-28`.
- **IMPORTS**: `hashlib`, `hmac`, `secrets`, `base64` or hex encoding.
- **GOTCHA**: This is not a production auth system; do not build sessions/tokens. The join/admin endpoints can return success and the UI can keep verification in `st.session_state`.
- **VALIDATE**: Manual Python snippet or via API smoke: correct password succeeds, wrong password returns 403.

### Task 4: Update repository for room fields and participant sessions
- **ACTION**: Update `ProjectEvaluationRepository`.
- **IMPLEMENT**:
  - `create_evaluation` stores `room_name`, password hashes, `project_name`, description.
  - `to_evaluation_read` returns `room_name` and never hashes.
  - Add `verify_admin_password(evaluation_id, password)` or service-level verification using `get_evaluation_row`.
  - Add `verify_room_password(evaluation_id, password)`.
  - Update `create_session(evaluation_id, participant_name="")` to store participant.
  - Update `to_session_read` to include `participant_name`.
- **MIRROR**: `create_evaluation` from `repository.py:73-86`, `create_session` from `repository.py:317-326`, converter methods from `repository.py:520-595`.
- **IMPORTS**: Existing SQLAlchemy imports should suffice.
- **GOTCHA**: Keep existing `create_session(evaluation_id)` compatibility by defaulting participant name, so realtime/admin flows do not break while code is being updated.
- **VALIDATE**: API smoke after router changes.

### Task 5: Add service methods for admin verify and student join
- **ACTION**: Update `ProjectEvaluationService`.
- **IMPLEMENT**:
  - `create_evaluation` validates room/password fields and passes hashes to repository or constructs a payload variant.
  - `verify_admin(evaluation_id, admin_password)` returns `{"ok": True}` or raises 403.
  - `join_evaluation(evaluation_id, room_password, participant_name)` verifies room password, ensures questions exist, creates `InterviewSession` with participant name, updates status to `INTERVIEWING`, returns session + interview URL path data.
  - Keep `create_session` for existing direct/admin flow, but student UI should use join.
  - `upload_zip` computes reason counts from saved artifacts: `metadata["reason"]` with `accepted` for extracted.
- **MIRROR**: Service HTTPException pattern from `service.py:199-205`; upload orchestration from `service.py:87-117`.
- **IMPORTS**: `HTTPException`, `status` already imported; add stdlib hashing imports if helpers live here.
- **GOTCHA**: Do not block professor upload/analysis behind real auth middleware. Admin verify is UI/API convenience for capstone, not full security.
- **VALIDATE**: Manual API calls: create room → upload → extract → generate → join.

### Task 6: Add API endpoints for admin verify and join
- **ACTION**: Update `router.py`.
- **IMPLEMENT**:
  - `POST /api/project-evaluations/{evaluation_id}/admin/verify`.
  - `POST /api/project-evaluations/{evaluation_id}/join`.
  - Response models from Task 1.
- **MIRROR**: Router dependency pattern from `router.py:42-64` and list response pattern from `router.py:91-106`.
- **IMPORTS**: New Pydantic classes from `domain.models`.
- **GOTCHA**: Keep current endpoints so existing Streamlit and realtime routes continue to work during transition.
- **VALIDATE**: OpenAPI page or direct `requests` smoke.

### Task 7: Fix artifact reporting semantics
- **ACTION**: Update `zip_handler.py`, `service.py`, `Home.py` display.
- **IMPLEMENT**:
  - Keep `ignored` for ignored binaries/vendor files.
  - For `file_too_large` and `empty_text`, preserve `source_type` from classifier instead of setting every skipped artifact to `IGNORED` unless truly ignored.
  - In service upload result, include `reason_counts` from metadata.
  - In Streamlit analysis screen, replace `제외/실패` metric with multiple metrics: `추출 성공`, `무시됨`, `텍스트 없음`, `용량 초과`, `처리 제한`, `실패`.
  - Add expander with examples from `artifacts` grouped by reason.
- **MIRROR**: `zip_handler.py:99-157` reason metadata and `Home.py:111-114` metric style.
- **IMPORTS**: `collections.Counter` in service if not already.
- **GOTCHA**: Current live DB showed `ignored=197`, `empty_text=9`, `file_too_large=2`, `failed=0`, `extracted=28`; the UI must make this distinction obvious.
- **VALIDATE**: Upload same zip and confirm actual failed count is 0 when no extraction exception occurred.

### Task 8: Improve project area inference to avoid generic `CLAUDE` areas
- **ACTION**: Update `context_builder.py`.
- **IMPLEMENT**:
  - In `_infer_project_areas`, de-prioritize root docs/config files like `CLAUDE.md`, `README.md`, `pyproject.toml`, lock files.
  - Group code by meaningful path segments: if path starts with `app/modules/report/service.py`, area can be `app/modules/report`; if `tests/modules/report/...`, use `modules/report` as supporting refs rather than separate `tests` area.
  - Keep docs as refs attached to matching code area when names overlap; only create docs area if docs dominate and code is sparse.
  - Ensure each area has source refs with snippets from real extracted text.
- **MIRROR**: Existing output shape from `context_builder.py:217-239` must remain `{name, summary, confidence, source_refs}`.
- **IMPORTS**: `PurePosixPath`, `Counter` already present.
- **GOTCHA**: Do not over-engineer static analysis. Simple path heuristics are enough for MVP.
- **VALIDATE**: Existing uploaded project should no longer create Q1 as `CLAUDE 영역...`; area names should resemble feature/module names.

### Task 9: Replace generic fallback question generation with source-grounded questions
- **ACTION**: Update `question_generator.py`.
- **IMPLEMENT**:
  - Remove or stop using `QUESTION_TEMPLATES` as the primary fallback.
  - Build fallback questions from `area.source_refs_json`: include 1-3 file paths and snippet-derived keywords.
  - Generate 5 questions with Bloom sequence, but each question must mention concrete files or modules.
  - Example output shape:
    - `app/core/upstage.py와 app/main.py를 기준으로, 외부 API 호출 결과가 FastAPI 응답까지 이어지는 흐름을 설명해주세요.`
    - `docs/report-data-contract.md와 app/modules/report/service.py의 리포트 구조가 어떻게 맞물리는지 설명해주세요.`
  - If source refs are empty, use context summary/features/artifacts snippets before falling back to “프로젝트 전체”.
  - Add a clear marker in `expected_signal` when fallback was used: `자료 발췌 기반 fallback 질문입니다...`.
- **MIRROR**: Keep return dict keys from `question_generator.py:124-135` exactly.
- **IMPORTS**: Existing `from_json`, `DEFAULT_RUBRIC`, `BLOOM_SEQUENCE`.
- **GOTCHA**: The user specifically called out `CLAUDE 영역에서 핵심 흐름...` as unacceptable. Do not generate questions with only `{area}` substitution.
- **VALIDATE**: Regenerate questions and inspect preview; every question should have source refs and at least one concrete path/module term.

### Task 10: Split Streamlit into professor/admin and student modes
- **ACTION**: Update `apps/streamlit/Home.py`.
- **IMPLEMENT**:
  - Add `mode` in session state: `home`, `professor`, `student`.
  - Home screen with two choices.
  - Professor mode:
    - Create room form: room/exam name, project name, description, room password, admin password, optional candidate/team label.
    - After creation, show evaluation ID and student join instructions.
    - Admin management form: evaluation ID + admin password for existing room.
    - Upload/analyze/generate/report management after admin verified.
  - Student mode:
    - Join form: evaluation ID, participant name, room password.
    - On success, show realtime interview link built from `get_api_base_url() + /interview/{evaluation_id}/{session_id}`.
  - Preserve current `call_api` pattern.
- **MIRROR**: `st.form` and `st.session_state` pattern from `Home.py:23-46`, API call error handling from `Home.py:38-43`, link button from `Home.py:163-173`.
- **IMPORTS**: New API client functions.
- **GOTCHA**: Do not make students upload files or see admin analysis controls. Do not put password values in visible state after request if avoidable.
- **VALIDATE**: Manual click-through in Streamlit.

### Task 11: Extend API client wrappers
- **ACTION**: Update `apps/streamlit/api_client.py`.
- **IMPLEMENT**:
  - Update `create_evaluation(...)` signature to include room/admin fields.
  - Add `verify_admin(evaluation_id, admin_password)`.
  - Add `join_evaluation(evaluation_id, participant_name, room_password)`.
  - Keep `request_json_dict/list` unchanged.
- **MIRROR**: Existing wrapper style from `api_client.py:62-84`.
- **IMPORTS**: No new imports.
- **GOTCHA**: Preserve backward compatibility where possible; if tests call old signature, update test or provide defaults.
- **VALIDATE**: `apps/streamlit/test_api_client.py` may need tiny signature update.

### Task 12: Connect joined student session to Realtime without rewriting microphone logic
- **ACTION**: Use existing realtime URL; no major changes to `router_realtime.py` unless session validation requires participant display.
- **IMPLEMENT**:
  - Student join returns `session.id`.
  - Streamlit student mode builds `/interview/{evaluation_id}/{session_id}`.
  - Optionally display participant/session metadata on HTML page by sending an `info` message from `run_realtime_session` caller, but only if simple.
- **MIRROR**: Current URL construction in `Home.py:163-165`; realtime session completion from `service.py:345-365`.
- **IMPORTS**: Likely none.
- **GOTCHA**: User says microphone permission works. Do not rewrite `startMic()`/`getUserMedia` unless broken by other changes.
- **VALIDATE**: Student join → click link → realtime page loads.

### Task 13: Minimal PRD/doc update
- **ACTION**: Update PRD Phase table and details.
- **IMPLEMENT**:
  - Add Phase 8 row with `in-progress` and this plan path.
  - Note that realtime microphone is functioning and current focus is room/artifact/question repair.
- **MIRROR**: PRD table format from `.claude/PRPs/prds/fastapi-streamlit-project-evaluation.prd.md:156-167`.
- **IMPORTS**: N/A.
- **GOTCHA**: Do not reintroduce manyfast or old backend/frontend assumptions.
- **VALIDATE**: Read PRD section after edit.

---

## Testing Strategy

The user explicitly said: “테스트 작성할 시간에 기능을 구현해라.” Follow this by prioritizing implementation and manual smoke verification. Only update existing tests if the changed schema breaks them.

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| Existing `test_create_evaluation` | New create payload with room fields | 200 and room name present | No |
| Existing `test_upload_zip` | Fixture zip | `accepted_count >= 1`, reason counts present | No |
| Existing `test_generate_questions` | Fixture context | Questions include `source_refs` and concrete file path terms | Yes |
| Optional tiny join test | Correct/wrong room password | Correct creates session, wrong returns 403 | Yes |

### Edge Cases Checklist
- [ ] Zip with many ignored binaries displays ignored count, not failure count.
- [ ] Zip with empty text files displays empty-text count.
- [ ] LLM disabled still generates source-grounded questions.
- [ ] Wrong room password cannot create student session.
- [ ] Wrong admin password cannot access professor controls.
- [ ] Existing DB without new columns is handled or reset instructions are clear.
- [ ] Student session can reach realtime URL.
- [ ] Realtime completion still maps answer texts to questions by order.

---

## Validation Commands

### Static Analysis
```bash
uv run ruff check .
```
EXPECT: Zero lint errors.

### Minimal Existing Tests
```bash
uv run pytest services/api/tests/test_evaluation_api.py apps/streamlit/test_api_client.py
```
EXPECT: Existing API/client tests pass after minimal schema updates.

### Full Test Suite
```bash
uv run pytest
```
EXPECT: No regressions. If time is limited, prioritize the minimal existing tests and manual smoke below.

### Database Validation
```bash
python - <<'PY'
import sqlite3
con = sqlite3.connect('data/app.db')
for table in ['project_evaluations', 'interview_sessions']:
    print(table)
    for row in con.execute(f'pragma table_info({table})'):
        print(row[1], row[2])
con.close()
PY
```
EXPECT: `project_evaluations` includes `room_name`, `room_password_hash`, `admin_password_hash`; `interview_sessions` includes `participant_name`.

### Browser Validation
```bash
uv run uvicorn services.api.app.main:app --reload
uv run streamlit run apps/streamlit/Home.py
```
EXPECT: Streamlit opens; professor can create/manage room; student can join and open realtime interview.

### Manual Validation
- [ ] Professor mode creates a room with room/admin passwords.
- [ ] Professor upload shows separated counts: extracted/ignored/empty/large/failed.
- [ ] Ignored files are not labeled as failures.
- [ ] Context generation completes.
- [ ] Question preview no longer starts with `CLAUDE 영역에서...`.
- [ ] Each generated/fallback question mentions concrete source files/modules.
- [ ] Student mode joins with correct room password.
- [ ] Wrong room password is rejected.
- [ ] Student realtime link opens existing microphone flow.
- [ ] Interview completion still generates a report.
- [ ] Professor can refresh/view latest report.

---

## Acceptance Criteria
- [ ] Upload result distinguishes ignored/skipped reasons from actual failures.
- [ ] “제외/실패 208개” style misleading metric is removed.
- [ ] Fallback question generation is source-grounded and not generic.
- [ ] Generated questions display source references in Streamlit.
- [ ] Professor can create a room/exam with room name, room password, admin password.
- [ ] Professor/admin can upload zip, analyze context, generate questions, view reports.
- [ ] Student can join with evaluation ID/URL + name + room password.
- [ ] Student join creates an `InterviewSession` with participant name.
- [ ] Student realtime interview URL uses the joined session.
- [ ] Existing Realtime microphone permission logic remains working.
- [ ] Existing tests pass or are minimally updated for schema changes.
- [ ] Manual golden path succeeds.

## Completion Checklist
- [ ] Code follows discovered FastAPI service/repository/router patterns.
- [ ] Error handling uses existing Korean `HTTPException` style.
- [ ] Logging remains minimal and follows realtime logger style where needed.
- [ ] No new runtime dependencies added.
- [ ] No password stored in plaintext.
- [ ] No full login/auth system introduced.
- [ ] No unnecessary test expansion.
- [ ] PRD Phase 8 points to this plan.
- [ ] Self-contained — no additional codebase search needed during implementation.

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Existing SQLite DB lacks new columns | High | API crashes after model update | Add tiny schema patch or reset demo DB; prefer schema patch. |
| Scope expands into full auth | Medium | Delays MVP | Only hash/verify room/admin password; no accounts/tokens. |
| Fallback questions still too generic | Medium | Core product value fails | Require source path terms in every fallback question. |
| LLM failures remain invisible | Medium | Debugging hard | Add UI/metadata note for fallback mode; do not silently imply LLM success. |
| Streamlit state becomes tangled | Medium | Professor/student flows bleed together | Explicit `mode`, `admin_verified`, `joined_session`; reset button clears all. |
| Realtime answer mapping remains order-based | Medium | Follow-up answers may mis-map | Keep current MVP mapping but ensure questions are ordered and session-specific. |
| Tests consume time | Low | Delays feature | Only run/update existing tests; rely on manual smoke. |

## Notes
- Live DB inspection showed latest upload had `ignored=197`, `empty_text=9`, `file_too_large=2`, `failed=0`, `extracted=28`. The current UI collapses these into “제외/실패,” causing a false failure impression.
- Current question preview showed `CLAUDE 영역에서 핵심 흐름...`, proving fallback templates are being used and are too generic.
- User confirmed microphone permission works; do not spend time redesigning `getUserMedia`.
- The existing `.claude/PRPs/plans/webui-exam-room-flow.plan.md` is for the old multi-repo/backend/frontend/manyfast context and must not be used as the implementation source for v2. This plan supersedes it for v2.
