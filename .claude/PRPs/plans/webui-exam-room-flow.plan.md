# Plan: WebUI Exam Room Flow

## Fact-Forcing Gate Facts

1. **Caller file(s)/line(s)**: 이 파일은 실행 코드가 직접 호출하지 않는 PRP 계획 산출물이며, 후속 `/prp-implement .claude/PRPs/plans/webui-exam-room-flow.plan.md` 명령의 입력으로 사용된다.
2. **Existing-file check**: `rtk proxy find .claude/PRPs/plans -maxdepth 1 -type f \( -name '*room*.plan.md' -o -name '*exam*.plan.md' -o -name '*webui*.plan.md' \) -print` 결과 동일 목적의 기존 계획 파일이 없었다.
3. **Data structure**: 이 계획 파일은 Markdown 텍스트만 저장한다. 코드에서 읽고 쓰는 데이터 파일이 아니며, 예시 API payload는 synthetic 값만 사용한다. 날짜 예시는 ISO 8601 형식(`2026-05-08T00:00:00Z`)이다.
4. **User instruction verbatim**: “현재 CLI의 기능을 WebUI에서 사용할 수 있게 만들기.
기존 CLI 흐름을 참고하고, 백엔드 API는 아직 없으면 필요한 API 계약까지 포함해줘.

WebUI에서는 아래 기능을 포함해야됨
1. 시험을 볼 수 있는 방을 만든다. 방을 만들기 위해선 [방 이름, 비밀번호, 관리자 비밀번호]를 입력해야 한다.
2. 방을 만들면 방의 URL이 나온다. 다른 사용자는 이 URL을 이용해서 시험에 참여할 수 있다. 참여하기 위해선 비밀번호 입력이 필요하다.”
5. **Clarified policy**: 방은 곧 시험을 의미한다. 참여는 URL + 학생 이름 + 방 비밀번호로 한다. 관리자 비밀번호는 방 관리 인증에 사용한다.

## Summary
CLI의 `ExamConfig -> question generation -> answer/follow-up -> report` 흐름을 WebUI에서 사용할 수 있도록, “방=시험”이라는 별도 guest room exam 흐름을 추가한다. 교수자/관리자는 방 이름, 방 비밀번호, 관리자 비밀번호만으로 방을 만들고 참여 URL을 공유하며, 학생은 URL + 학생 이름 + 방 비밀번호로 로그인 없이 시험에 참여한다.

## User Story
As a 교수자/관리자,
I want 방 이름과 비밀번호로 시험 방을 만들고 참여 URL을 공유할 수 있기를,
so that 학생들이 별도 앱 로그인 없이 URL로 시험에 참여할 수 있다.

As a 학생,
I want 참여 URL에서 학생 이름과 방 비밀번호만 입력해 시험에 들어가기를,
so that CLI에서 하던 대화형 시험을 WebUI에서 바로 응시할 수 있다.

## Problem → Solution
현재 시험 응시는 CLI 인자와 터미널 입력에 묶여 있고, 기존 Web 백엔드는 로그인한 학생의 `ExamSession`만 지원한다. → 새 `room` 도메인을 추가해 공개 참여 URL, 학생 이름 기반 guest participant, 방/관리자 비밀번호 검증, room-bound exam session API를 제공하고, 프론트엔드에는 방 생성/URL 표시/참여 화면을 추가한다.

## Metadata
- **Complexity**: XL
- **Source PRD**: manyfast project `6399f301-af9a-4e70-b856-2b5707e72088`, feature `F-MWLZWY`, spec `S-SNAUBV`
- **PRD Phase**: standalone
- **Estimated Files**: 40+

---

## UX Design

### Before
```text
┌─────────────────────────────┐
│ CLI only                    │
│ 1. 명령어 인자 입력          │
│ 2. 터미널에서 문제 표시      │
│ 3. 터미널/마이크로 답변      │
│ 4. JSON 리포트 저장          │
└─────────────────────────────┘

┌─────────────────────────────┐
│ Current Web                 │
│ 학생 로그인 필요             │
│ /student/exams/{examId}      │
│ 기존 계정 기반 세션만 지원   │
└─────────────────────────────┘
```

### After
```text
┌─────────────────────────────┐
│ 방 생성                     │
│ 방 이름                     │
│ 방 비밀번호                 │
│ 관리자 비밀번호             │
│ [방 만들기]                 │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ 참여 URL 발급               │
│ /rooms/{slug}               │
│ [복사] [관리 화면]          │
└──────────────┬──────────────┘
               │ 공유
               ▼
┌─────────────────────────────┐
│ 학생 참여                   │
│ 학생 이름                   │
│ 방 비밀번호                 │
│ [시험 참여]                 │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Web 대화형 시험             │
│ 질문/답변/꼬리질문/완료     │
└─────────────────────────────┘
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| 시험 생성 | CLI args 또는 교수자 로그인 기반 exam 생성 | 방 이름/비밀번호/관리자 비밀번호로 guest exam room 생성 | `방=시험` 정책 |
| 학생 인증 | 로그인한 학생 계정 필요 | URL + 학생 이름 + 방 비밀번호 | 별도 guest participant 세션 필요 |
| 관리 인증 | 교수자 로그인 | 관리자 비밀번호 | 방 관리 화면 전용 |
| 시험 진행 | CLI stdin/audio 또는 로그인 학생 Web session | room participant session 기반 Web UI | 기존 `StudentExamSessionPage` UI 패턴 재사용 |

---

## Mandatory Reading

Files that MUST be read before implementing:

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `cli/CLAUDE.md` | 1-120 | CLI MVP 구조와 Web migration 원칙 |
| P0 | `cli/cli_take_exam.py` | 19-98 | CLI entry point와 `ExamConfig` 구성 방식 |
| P0 | `cli/models.py` | 111-244 | `ExamConfig`, `GeneratedQuestion`, `QuestionExchange`, `ExamReport` 계약 |
| P0 | `cli/exam_session_graph.py` | 38-70, 107-205 | Web/API에 가장 가까운 interrupt 기반 세션 상태 구조 |
| P0 | `backend/CLAUDE.md` | 66-129 | Hexagonal Architecture와 새 도메인 추가 순서 |
| P0 | `backend/app/exam/application/service/exam.py` | 199-343, 723-1041 | 기존 시험 availability, student session, turn/follow-up/result 흐름 |
| P0 | `backend/app/exam/adapter/input/api/v1/exam.py` | 69-70, 601-751 | 기존 student session API route shape |
| P0 | `frontend/CLAUDE.md` | 47-174 | FSD 구조, App Router, API/TanStack Query, UI 검증 규칙 |
| P1 | `backend/core/fastapi/router.py` | 25-40 | 도메인 router 등록 위치 |
| P1 | `backend/app/container.py` | 13-32 | dependency-injector container 등록 위치 |
| P1 | `backend/app/classroom/adapter/input/api/v1/classroom.py` | 35-74 | router/request/command/response mapping 예시 |
| P1 | `backend/app/classroom/application/service/classroom.py` | 74-119 | service transaction, auth, duplicate check 패턴 |
| P1 | `backend/core/helpers/argon2.py` | 5-23 | 비밀번호 hash/verify 유틸 |
| P1 | `backend/core/db/sqlalchemy/models/base.py` | 6-37 | BaseTable 공통 column 패턴 |
| P1 | `backend/core/db/sqlalchemy/__init__.py` | 12-25 | ORM mapper init 등록 위치 |
| P1 | `frontend/src/shared/api/client.ts` | 31-140 | fetch wrapper, error handling, credentials 패턴 |
| P1 | `frontend/src/features/create-classroom/ui/form.tsx` | 16-139 | HeroUI form + mutation + error message 패턴 |
| P1 | `frontend/src/entities/exam/api/query.ts` | 46-150, 199-245 | entity API와 query hook 패턴 |
| P1 | `frontend/src/widgets/student-exam-session/student-exam-session-page.tsx` | 162-279 | turn payload와 existing exam session UI 구조 |
| P2 | `backend/tests/app/exam/adapter/input/test_exam_session_api.py` | 27-85 | API test monkeypatch/cookie fixture 패턴 |
| P2 | `frontend/src/app/professor/classrooms/[classroomId]/exams/[examId]/page.tsx` | 16-37 | Next 16 `params: Promise`와 server fetch 패턴 |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| Next.js App Router dynamic params | Context7 `/vercel/next.js/v16.2.2` | Next 15+에서 server page/layout의 `params`는 Promise이므로 `const { slug } = await params` 패턴 사용 |
| Next.js client navigation | Context7 `/vercel/next.js/v16.2.2` | client component event handler에서 `useRouter().push()`/`replace()` 사용 |
| HeroUI v3 forms | Context7 `/llmstxt/heroui_react_llms_txt` | `TextField`가 `Label`, `Input`, `FieldError`/`ErrorMessage`와 함께 accessible form wrapper 역할 |
| TanStack Query v5 mutation invalidation | Context7 `/tanstack/query/v5.90.3` | `useMutation({ onSuccess: async () => await queryClient.invalidateQueries(...) })` 패턴 유지 |

---

## Patterns to Mirror

### NAMING_CONVENTION_BACKEND
// SOURCE: `backend/CLAUDE.md:116-129`
```text
새 도메인 추가 순서:
1. domain entity/value object 작성
2. command 모델 작성
3. repository port 정의
4. use-case interface 정의
5. application service 구현
6. request/response schema 작성
7. router 추가
8. output persistence adapter 구현
9. container.py wiring
10. domain/application/API/persistence 테스트 추가

명명은 CreateThingRequest, CreateThingCommand, ThingPayload,
ThingResponse, ThingUseCase, ThingRepository처럼 역할이 드러나게 한다.
```

### ROUTER_PATTERN
// SOURCE: `backend/app/classroom/adapter/input/api/v1/classroom.py:32-60`
```python
router = APIRouter(prefix="/classrooms", tags=["classrooms"])

@router.post(
    "",
    response_model=ClassroomResponse,
    dependencies=[Depends(PermissionDependency([IsProfessorOrAdmin]))],
)
@inject
async def create_classroom(
    request: CreateClassroomRequest,
    current_user: CurrentUser = Depends(get_current_user),
    usecase: ClassroomUseCase = Depends(Provide[ClassroomContainer.service]),
):
    classroom = await usecase.create_classroom(
        current_user=current_user,
        command=CreateClassroomCommand(...),
    )
    return ClassroomResponse(data=ClassroomPayload(...))
```

For public room join routes, omit `PermissionDependency` and `get_current_user`; inject `RoomUseCase` only.

### SERVICE_PATTERN
// SOURCE: `backend/app/classroom/application/service/classroom.py:74-119`
```python
@transactional
async def create_classroom(...):
    if current_user.role not in (UserRole.PROFESSOR, UserRole.ADMIN):
        raise AuthForbiddenException()

    classroom = Classroom.create(...)
    existing_classroom = await self.repository.get_by_organization_and_name_and_term(...)
    if existing_classroom is not None:
        raise ClassroomAlreadyExistsException()

    await self.repository.save(classroom)
    return classroom
```

Room creation mirrors this with `Room.create(...)`, duplicate `slug` retry/check, Argon2 password hashing, and `repository.save(room)` inside `@transactional`.

### ERROR_HANDLING
// SOURCE: `backend/core/fastapi/listener.py:11-34`, `backend/app/exam/application/exception/exam.py:72-87`
```python
@app.exception_handler(CustomException)
async def custom_exception_handler(_: Request, exc: CustomException):
    return JSONResponse(
        status_code=exc.code,
        content={
            "error_code": exc.error_code,
            "message": exc.message,
            "detail": exc.detail,
        },
    )

class ExamSessionUnavailableException(CustomException):
    code = 409
    error_code = "EXAM_SESSION__UNAVAILABLE"
    message = "현재 이 평가에 입장할 수 없습니다."
```

Add room exceptions such as `ROOM__NOT_FOUND`, `ROOM__INVALID_PASSWORD`, `ROOM__CLOSED`, `ROOM_PARTICIPANT__NOT_FOUND`, `ROOM_ADMIN__INVALID_PASSWORD`.

### PASSWORD_HASH_PATTERN
// SOURCE: `backend/core/helpers/argon2.py:5-23`
```python
class Argon2Helper:
    _ph = PasswordHasher()

    @classmethod
    def hash(cls, password: str) -> str:
        return cls._ph.hash(password)

    @classmethod
    def verify(cls, password: str, hashed_password: str) -> bool:
        try:
            return cls._ph.verify(hashed_password, password)
        except VerifyMismatchError:
            return False
```

Never store room password or admin password in plaintext.

### REPOSITORY_PATTERN
// SOURCE: `backend/app/classroom/adapter/output/persistence/sqlalchemy/classroom.py:12-57`
```python
class ClassroomSQLAlchemyRepository(ClassroomRepository):
    async def get_by_id(self, entity_id: UUID) -> Classroom | None:
        query = select(Classroom).where(classroom_table.c.id == entity_id)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def save(self, entity: Classroom) -> None:
        session.add(entity)
```

Room repositories should use SQLAlchemy imperative mapping, repository ports, and `session.add(entity)`.

### API_RESPONSE_PATTERN
// SOURCE: `backend/app/classroom/adapter/input/api/v1/response/__init__.py:9-26`
```python
class ClassroomPayload(BaseModel):
    id: str
    name: str

class ClassroomResponse(BaseResponse):
    data: ClassroomPayload = Field(default=...)
```

Use `RoomPayload`, `RoomPublicPayload`, `RoomParticipantPayload`, `RoomAdminPayload`, all wrapped in `BaseResponse`.

### FRONTEND_ENTITY_API_PATTERN
// SOURCE: `frontend/src/entities/classroom/api/query.ts:13-47`
```ts
export const classroomsApi = {
    createClassroom: async (payload: CreateClassroomRequest): Promise<Classroom> => {
        const response = await apiClient.post<ApiResponse<Classroom>>('/api/classrooms', payload);
        return response.data;
    },
};
```

Create `src/entities/room/api/query.ts` with `roomsApi.createRoom`, `getPublicRoom`, `joinRoom`, `verifyAdmin`, `getAdminRoom`, `closeRoom`, etc.

### FRONTEND_MUTATION_PATTERN
// SOURCE: `frontend/src/features/create-exam/model/use-create-exam.ts:8-17`
```ts
export const useCreateExam = (classroomId: string) => {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (payload: CreateExamRequest) => examsApi.createExam(classroomId, payload),
        onSuccess: async (exam) => {
            await queryClient.invalidateQueries({ queryKey: getClassroomExamsQueryKey(classroomId) });
            queryClient.setQueryData(getClassroomExamDetailQueryKey(classroomId, exam.id), exam);
        },
    });
};
```

Room mutations should set `getRoomAdminQueryKey(roomId)` after creation/join when the API returns enough data.

### FRONTEND_FORM_PATTERN
// SOURCE: `frontend/src/features/create-classroom/ui/form.tsx:28-70`
```tsx
const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setErrorMessage(null);

    const formData = new FormData(event.currentTarget);
    const name = String(formData.get('name') ?? '').trim();

    try {
        const classroom = await createClassroom(payload);
        router.replace(`/professor/classrooms/${classroom.id}`);
        router.refresh();
    } catch (error) {
        if (error instanceof ApiClientError) {
            setErrorMessage(error.message);
            return;
        }
        setErrorMessage('강의실 생성 중 오류가 발생했습니다.');
    }
};
```

Room forms use the same `FormData`, local `errorMessage`, `ApiClientError` handling, HeroUI `TextField`, `Label`, `Input`, `ErrorMessage`, `Button` pattern.

### NEXT_APP_ROUTER_PATTERN
// SOURCE: `frontend/src/app/professor/classrooms/[classroomId]/exams/[examId]/page.tsx:16-37`
```tsx
export default async function ProfessorExamManagementPage({ params }: ProfessorExamManagementPageProps) {
    const { classroomId, examId } = await params;
    const cookieStore = await cookies();
    const accessToken = cookieStore.get(ACCESS_TOKEN_COOKIE_NAME)?.value;
    const [classroomData, materialsData, examData] = await Promise.all([...]);

    return <ExamManagementScreen ... />;
}
```

Public room pages do not need auth cookies, but should still use `params: Promise<{ roomSlug: string }>` for Next 16.

### EXAM_SESSION_TURN_PATTERN
// SOURCE: `frontend/src/widgets/student-exam-session/student-exam-session-page.tsx:162-179`
```ts
function buildTurnPayload(
    question: StudentExamSessionQuestion,
    content: string,
    metadata: Record<string, string> = {},
): RecordExamTurnRequest {
    return {
        role: 'student',
        event_type: 'answer',
        content,
        metadata: {
            question_id: question.id,
            question_type: question.question_type,
            input_mode: getQuestionInputMode(question.question_type),
            ...metadata,
        },
        occurred_at: new Date().toISOString(),
    };
}
```

If reusing the existing session UI for room participants, introduce room-specific type aliases and `roomsApi.recordTurn(...)` but preserve this payload shape.

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `backend/app/room/domain/entity/__init__.py` | CREATE | `Room`, `RoomParticipant`, status enums, password verification methods |
| `backend/app/room/domain/command/__init__.py` | CREATE | `CreateRoomCommand`, `JoinRoomCommand`, `VerifyRoomAdminCommand`, room turn/session commands |
| `backend/app/room/domain/repository/__init__.py` | CREATE | `RoomRepository`, `RoomParticipantRepository`, optional `RoomTurnRepository` ports |
| `backend/app/room/domain/usecase/__init__.py` | CREATE | `RoomUseCase` interface |
| `backend/app/room/application/exception/__init__.py` | CREATE | Room-specific `CustomException` classes |
| `backend/app/room/application/service/room.py` | CREATE | Room create/join/admin/session orchestration |
| `backend/app/room/application/service/__init__.py` | CREATE | service export |
| `backend/app/room/adapter/input/api/v1/request/__init__.py` | CREATE | Pydantic request schemas |
| `backend/app/room/adapter/input/api/v1/response/__init__.py` | CREATE | response payload schemas |
| `backend/app/room/adapter/input/api/v1/room.py` | CREATE | public/admin room routes |
| `backend/app/room/adapter/output/persistence/sqlalchemy/room.py` | CREATE | SQLAlchemy repository implementations |
| `backend/app/room/container.py` | CREATE | DI wiring for room domain |
| `backend/app/container.py` | UPDATE | include `RoomContainer`, wiring package |
| `backend/core/fastapi/router.py` | UPDATE | include room router |
| `backend/core/db/sqlalchemy/models/room.py` | CREATE | `t_room`, `t_room_participant`, optional room session/turn/result tables |
| `backend/core/db/sqlalchemy/mapping/room.py` | CREATE | imperative ORM mappings |
| `backend/core/db/sqlalchemy/__init__.py` | UPDATE | initialize room mappers |
| `backend/alembic/versions/<new>_add_room_domain.py` | CREATE | room tables and constraints |
| `backend/tests/app/room/domain/test_room_entity.py` | CREATE | entity password/status/name rules |
| `backend/tests/app/room/application/test_room_service.py` | CREATE | create/join/admin behavior |
| `backend/tests/app/room/adapter/input/test_room_api.py` | CREATE | public API contract tests |
| `backend/tests/app/room/adapter/output/persistence/test_room_repository.py` | CREATE | persistence behavior |
| `frontend/src/entities/room/model/types.ts` | CREATE | Room, public room, participant/session request/response types |
| `frontend/src/entities/room/model/query-keys.ts` | CREATE | query keys |
| `frontend/src/entities/room/api/query.ts` | CREATE | `roomsApi`, hooks |
| `frontend/src/entities/room/index.ts` | CREATE | public API barrel |
| `frontend/src/features/create-room/model/use-create-room.ts` | CREATE | create mutation |
| `frontend/src/features/create-room/ui/form.tsx` | CREATE | create room form and URL result |
| `frontend/src/features/create-room/index.ts` | CREATE | feature export |
| `frontend/src/features/join-room/model/use-join-room.ts` | CREATE | join mutation |
| `frontend/src/features/join-room/ui/form.tsx` | CREATE | student name + password form |
| `frontend/src/features/join-room/index.ts` | CREATE | feature export |
| `frontend/src/features/verify-room-admin/...` | CREATE | admin password verification flow |
| `frontend/src/widgets/room-create/room-create-page.tsx` | CREATE | create room page composition |
| `frontend/src/widgets/room-join/room-join-page.tsx` | CREATE | public room join page |
| `frontend/src/widgets/room-admin/room-admin-page.tsx` | CREATE | room management page |
| `frontend/src/widgets/room-exam-session/room-exam-session-page.tsx` | CREATE | room participant exam UI, initially mirrors student session UI |
| `frontend/src/app/rooms/new/page.tsx` | CREATE | create room route |
| `frontend/src/app/rooms/[roomSlug]/page.tsx` | CREATE | public join route |
| `frontend/src/app/rooms/[roomSlug]/admin/page.tsx` | CREATE | admin route |
| `frontend/src/app/rooms/[roomSlug]/session/page.tsx` | CREATE | room participant session route |

## NOT Building

- 학교 연동 로그인/권한을 room participant flow에 강제하지 않는다.
- 기존 `StudentExamSessionPage`의 로그인 기반 `/student/exams` 목록을 제거하지 않는다.
- 실시간 음성 Realtime API 전체 통합을 첫 PR에서 완성하려고 하지 않는다.
- 방 비밀번호/관리자 비밀번호 평문 조회 API를 만들지 않는다.
- 대규모 리포트/분석 대시보드는 포함하지 않는다.
- 공개 URL만으로 관리자 작업을 허용하지 않는다. 관리자 비밀번호 검증이 필수다.

---

## Proposed Backend API Contract

### Create room
`POST /api/rooms`

Request:
```json
{
  "name": "자료구조 구술평가 1차",
  "password": "student-room-password",
  "admin_password": "admin-room-password"
}
```

Response `200`:
```json
{
  "data": {
    "id": "uuid",
    "slug": "short-public-slug",
    "name": "자료구조 구술평가 1차",
    "status": "open",
    "participant_url": "http://localhost:3000/rooms/short-public-slug",
    "admin_url": "http://localhost:3000/rooms/short-public-slug/admin",
    "created_at": "2026-05-08T00:00:00Z"
  }
}
```

### Get public room info
`GET /api/rooms/{room_slug}/public`

Response:
```json
{
  "data": {
    "slug": "short-public-slug",
    "name": "자료구조 구술평가 1차",
    "status": "open"
  }
}
```

### Join room
`POST /api/rooms/{room_slug}/participants`

Request:
```json
{
  "student_name": "김민준",
  "password": "student-room-password"
}
```

Response:
```json
{
  "data": {
    "participant_id": "uuid",
    "room_id": "uuid",
    "room_slug": "short-public-slug",
    "student_name": "김민준",
    "session_token": "opaque-token",
    "session_url": "http://localhost:3000/rooms/short-public-slug/session"
  }
}
```

Token policy for MVP:
- Prefer `HttpOnly` cookie `room_participant_token` scoped to `/api/rooms/{room_slug}` if feasible.
- If cookie support is deferred, return `session_token` and store it in `sessionStorage`; send it as `Authorization: Bearer <token>` through a room-specific API client wrapper. This is acceptable for capstone MVP but should be documented as non-production.

### Verify admin
`POST /api/rooms/{room_slug}/admin/verify`

Request:
```json
{
  "admin_password": "admin-room-password"
}
```

Response:
```json
{
  "data": {
    "room_id": "uuid",
    "slug": "short-public-slug",
    "admin_token": "opaque-token",
    "participant_url": "http://localhost:3000/rooms/short-public-slug"
  }
}
```

### Admin get/update room
`GET /api/rooms/{room_slug}/admin` with admin auth token.

`PATCH /api/rooms/{room_slug}/admin` with admin auth token.

Request examples:
```json
{ "status": "closed" }
```
```json
{ "password": "new-student-password" }
```

### Room exam/session endpoints
- `GET /api/rooms/{room_slug}/session-sheet`
- `POST /api/rooms/{room_slug}/sessions`
- `POST /api/rooms/{room_slug}/sessions/{session_id}/turns`
- `POST /api/rooms/{room_slug}/sessions/{session_id}/follow-ups`
- `POST /api/rooms/{room_slug}/sessions/{session_id}/complete`
- `GET /api/rooms/{room_slug}/sessions/{session_id}/result`

Payloads should mirror existing `/api/exams/{exam_id}/...` response shapes from `ExamSessionPayload`, `StudentExamSessionSheetPayload`, `ExamTurnPayload`, and `ExamResultPayload` where possible.

---

## Step-by-Step Tasks

### Task 1: Backend room domain skeleton
- **ACTION**: Create `app/room` hexagonal module.
- **IMPLEMENT**: `RoomStatus`, `Room`, `RoomParticipant`, password verification, close/reopen methods.
- **MIRROR**: `backend/CLAUDE.md:116-129`, `backend/core/helpers/argon2.py:5-23`
- **IMPORTS**: `dataclasses`, `enum.StrEnum`, `uuid.UUID`, `core.common.entity`, `core.helpers.argon2.Argon2Helper`
- **GOTCHA**: Do not put FastAPI/Pydantic imports in domain entity.
- **VALIDATE**: `uv run pytest tests/app/room/domain/test_room_entity.py -q`

### Task 2: Backend commands/usecase/repositories/exceptions
- **ACTION**: Define application boundary contracts.
- **IMPLEMENT**: room create/join/admin/update commands, repository ports, usecase methods, room exceptions.
- **MIRROR**: `backend/app/classroom/domain/command/__init__.py:8-18`, `backend/app/exam/domain/usecase/exam.py:107-176`
- **IMPORTS**: `pydantic.BaseModel`, `Field`, `abc.abstractmethod`, `UUID`, `Sequence`
- **GOTCHA**: Request schemas and command schemas are separate.
- **VALIDATE**: `uv run python -c "from app.room.domain.command import CreateRoomCommand; print(CreateRoomCommand)"`

### Task 3: Backend persistence tables, mappers, repositories, migration
- **ACTION**: Add SQLAlchemy room persistence.
- **IMPLEMENT**: `t_room`, `t_room_participant`, mapper registration, repository implementations, Alembic migration.
- **MIRROR**: `backend/core/db/sqlalchemy/models/classroom.py:14-44`, `backend/core/db/sqlalchemy/mapping/exam.py:25-71`, `backend/app/exam/adapter/output/persistence/sqlalchemy/exam.py:25-107`
- **IMPORTS**: `sqlalchemy.Column`, `String`, `Enum`, `ForeignKey`, `Index`, `UniqueConstraint`, `select`, `session`
- **GOTCHA**: `BaseTable` automatically adds `created_at`, `updated_at`, `version_id`.
- **VALIDATE**: `ENVIRONMENT=test ... uv run alembic upgrade head` and repository tests.

### Task 4: Backend room service
- **ACTION**: Implement room create/join/admin orchestration.
- **IMPLEMENT**: unique slug generation, hashed passwords, participant token hash, admin token verification, close/update.
- **MIRROR**: `backend/app/classroom/application/service/classroom.py:74-119`, `backend/app/exam/application/service/exam.py:723-788`
- **IMPORTS**: `@transactional`, `secrets`, `datetime.UTC`, `Argon2Helper`, room repositories
- **GOTCHA**: Raw participant/admin token must never be persisted; persist only hash.
- **VALIDATE**: `uv run pytest tests/app/room/application/test_room_service.py -q`

### Task 5: Backend API routes and payload builders
- **ACTION**: Add room API router.
- **IMPLEMENT**: public/admin routes, request/response schemas, router registration, container wiring.
- **MIRROR**: `backend/app/exam/adapter/input/api/v1/exam.py:601-751`, `backend/app/classroom/adapter/input/api/v1/request/__init__.py:9-42`, `backend/app/exam/adapter/input/api/v1/response/__init__.py:130-142`
- **IMPORTS**: `APIRouter`, `Depends`, `Provide`, `inject`, `RoomContainer`
- **GOTCHA**: Public join routes must not use `PermissionDependency([IsAuthenticated])`.
- **VALIDATE**: `uv run pytest tests/app/room/adapter/input/test_room_api.py -q`

### Task 6: Backend room session bridge
- **ACTION**: Connect room participant flow to exam session behavior.
- **IMPLEMENT**: room-specific session endpoints; identify actor by `RoomParticipant`; mirror existing exam payload shapes.
- **MIRROR**: `cli/exam_session_graph.py:38-70`, `backend/app/exam/application/service/exam.py:811-935`, `frontend/src/widgets/student-exam-session/student-exam-session-page.tsx:162-179`
- **IMPORTS**: existing exam domain service ports where possible.
- **GOTCHA**: Existing `ExamService.start_exam_session` requires `current_user.role == STUDENT`; do not call it directly for guest participants unless intentionally refactored.
- **VALIDATE**: API tests for session start/turn/follow-up/complete using participant token.

### Task 7: Frontend room entity slice
- **ACTION**: Create `entities/room`.
- **IMPLEMENT**: types, query keys, API functions, hooks.
- **MIRROR**: `frontend/src/entities/exam/api/query.ts:46-150`, `frontend/src/entities/classroom/api/query.ts:13-47`
- **IMPORTS**: `apiClient`, `ApiResponse`, `useQuery`, `useMutation`, `useQueryClient`
- **GOTCHA**: If using participant/admin token headers, add room-specific API helpers without weakening global auth refresh behavior.
- **VALIDATE**: `yarn lint` after files are added.

### Task 8: Frontend create room flow
- **ACTION**: Add room creation page and feature.
- **IMPLEMENT**: `/rooms/new`, fields for room name/password/admin password, success URL display and copy buttons.
- **MIRROR**: `frontend/src/features/create-classroom/ui/form.tsx:16-139`, `frontend/src/app/professor/classrooms/new/page.tsx:3-19`
- **IMPORTS**: `Button`, `TextField`, `Label`, `Input`, `ErrorMessage`, `useCreateRoom`, `ApiClientError`
- **GOTCHA**: Do not navigate away immediately after create; user must see and copy the URL.
- **VALIDATE**: Browser check: create room with valid fields, see URLs, copy works.

### Task 9: Frontend join room flow
- **ACTION**: Add public join page.
- **IMPLEMENT**: `/rooms/[roomSlug]`, public room info, student name + password, route to session on success.
- **MIRROR**: Next params pattern from `frontend/src/app/professor/classrooms/[classroomId]/exams/[examId]/page.tsx:16-24`, form pattern from `CreateClassroomForm`.
- **IMPORTS**: `useRouter`, `useJoinRoom`, `ApiClientError`, HeroUI form components
- **GOTCHA**: This page is public; do not call `useViewer` or redirect unauthenticated users to login.
- **VALIDATE**: Browser check: wrong password shows API error; correct password enters session route.

### Task 10: Frontend admin management flow
- **ACTION**: Add admin password verification and room management page.
- **IMPLEMENT**: `/rooms/[roomSlug]/admin`, password verification, URL display, close/reopen, password change controls.
- **MIRROR**: `CreateExamModal` modal/form error handling, TanStack mutation invalidation.
- **IMPORTS**: `roomsApi.verifyAdmin`, `roomsApi.updateRoom`, `Button`, `TextField`, `Chip`, `SurfaceCard`
- **GOTCHA**: Never display admin password or room password after creation.
- **VALIDATE**: Browser check: wrong admin password rejected; correct admin password reveals controls; close room blocks new joins.

### Task 11: Frontend room exam session UI
- **ACTION**: Create a room-specific session page that mirrors student exam session UI.
- **IMPLEMENT**: `RoomExamSessionPage`, room session sheet/start/turn/follow-up/complete/result APIs, reuse presentational components where safe.
- **MIRROR**: `frontend/src/widgets/student-exam-session/student-exam-session-page.tsx:270+`, `frontend/src/widgets/student-exam-session/session-controls.tsx:21-110`
- **IMPORTS**: room API hooks, existing UI components, `ApiClientError`
- **GOTCHA**: Existing widget types are `StudentExam...`; do not force-cast incompatible room data.
- **VALIDATE**: Manual answer submit, follow-up, complete, result flow.

### Task 12: Tests, lint, build, browser validation
- **ACTION**: Add backend tests and run full validations.
- **IMPLEMENT**: backend domain/service/API/persistence tests, frontend lint/build, browser validation.
- **MIRROR**: `backend/tests/app/exam/adapter/input/test_exam_session_api.py:27-85`, `backend/tests/app/classroom/adapter/input/test_classroom_api.py:38-120`
- **IMPORTS**: `pytest`, `TestClient`, `monkeypatch`
- **GOTCHA**: Frontend currently has no test script; do not invent brittle unit tests without adding tooling deliberately.
- **VALIDATE**: See Validation Commands.

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `Room.create` hashes passwords | name/password/admin_password | password hashes differ from raw inputs | Yes |
| `Room.verify_password` valid password | raw password | `True` | No |
| `Room.verify_password` invalid password | wrong password | `False` | Yes |
| closed room join | room status `closed` | `RoomClosedException` | Yes |
| join with empty student name | `student_name=""` | 422 or validation error | Yes |
| admin verify wrong password | wrong admin password | `ROOM_ADMIN__INVALID_PASSWORD` | Yes |
| duplicate slug generation | forced collision | retry/new slug | Yes |
| participant token validation | stored hash + raw token | resolves participant | Yes |

### Edge Cases Checklist
- [ ] Empty room name
- [ ] Empty room password
- [ ] Empty admin password
- [ ] Same value for room password and admin password: allow for MVP or reject explicitly; choose in service test
- [ ] Wrong room password
- [ ] Wrong admin password
- [ ] Closed room join
- [ ] Unknown room slug
- [ ] Duplicate student names in same room
- [ ] Participant token missing/invalid
- [ ] Browser refresh on session route
- [ ] Network failure during join
- [ ] Copy URL unsupported browser fallback

---

## Validation Commands

### Backend Static Analysis
```bash
cd /Users/user/Desktop/dev/univ/grade_4/intelligent-system-capstone/backend && uv run ruff check .
```
EXPECT: Zero lint errors

```bash
cd /Users/user/Desktop/dev/univ/grade_4/intelligent-system-capstone/backend && uv run ruff format --check .
```
EXPECT: Formatting passes

### Backend Unit/API Tests
```bash
cd /Users/user/Desktop/dev/univ/grade_4/intelligent-system-capstone/backend && uv run pytest tests/app/room -q
```
EXPECT: All room tests pass

```bash
cd /Users/user/Desktop/dev/univ/grade_4/intelligent-system-capstone/backend && uv run pytest tests/app/exam tests/app/classroom tests/app/room -q
```
EXPECT: No regressions in adjacent domains

### Backend Full Test Suite
```bash
cd /Users/user/Desktop/dev/univ/grade_4/intelligent-system-capstone/backend && uv run pytest
```
EXPECT: No regressions

### Database Validation
```bash
cd /Users/user/Desktop/dev/univ/grade_4/intelligent-system-capstone/backend && uv run alembic upgrade head
```
EXPECT: room tables are created and migrations apply cleanly

### Frontend Static Analysis
```bash
cd /Users/user/Desktop/dev/univ/grade_4/intelligent-system-capstone/frontend && yarn lint
```
EXPECT: Zero ESLint errors

```bash
cd /Users/user/Desktop/dev/univ/grade_4/intelligent-system-capstone/frontend && yarn build
```
EXPECT: Next/TypeScript build passes

### Browser Validation
```bash
cd /Users/user/Desktop/dev/univ/grade_4/intelligent-system-capstone/backend && uv run uvicorn main:app --reload
```
```bash
cd /Users/user/Desktop/dev/univ/grade_4/intelligent-system-capstone/frontend && yarn dev
```
EXPECT: Feature works in browser

### Manual Validation
- [ ] Open `/rooms/new`.
- [ ] Submit empty fields and confirm validation/error states.
- [ ] Create room with room name, password, admin password.
- [ ] Confirm participant URL and admin URL are displayed.
- [ ] Copy participant URL and open in a clean/private browser session.
- [ ] Enter wrong password and confirm error.
- [ ] Enter student name + correct password and confirm session route loads.
- [ ] Open admin URL, enter wrong admin password and confirm error.
- [ ] Enter correct admin password and confirm participant URL/status controls appear.
- [ ] Close room and confirm new join attempts are blocked.
- [ ] Reopen room or change room password and confirm updated behavior.
- [ ] Test responsive breakpoints: 320, 375, 768, 1024, 1440.
- [ ] Test keyboard navigation/focus states for create/join/admin forms.

---

## Acceptance Criteria
- [ ] 방 생성 폼은 방 이름, 방 비밀번호, 관리자 비밀번호를 입력받는다.
- [ ] 방 생성 성공 시 참여 URL이 표시되고 복사 가능하다.
- [ ] 학생은 참여 URL에서 학생 이름과 방 비밀번호로 로그인 없이 참여할 수 있다.
- [ ] 방 비밀번호가 틀리면 참여할 수 없다.
- [ ] 관리자 비밀번호로 방 관리 화면에 접근할 수 있다.
- [ ] 관리자 비밀번호가 틀리면 관리 기능에 접근할 수 없다.
- [ ] 방 비밀번호와 관리자 비밀번호는 평문 저장/응답하지 않는다.
- [ ] 기존 로그인 기반 `/student/exams` 흐름은 깨지지 않는다.
- [ ] Backend room tests pass.
- [ ] Frontend `yarn lint` and `yarn build` pass.
- [ ] Browser에서 create/join/admin golden path를 확인했다.

## Completion Checklist
- [ ] Code follows backend Hexagonal Architecture.
- [ ] Router remains thin: request→command→usecase→response only.
- [ ] Error handling uses `CustomException` and existing error envelope.
- [ ] Password handling uses `Argon2Helper` or equivalent existing helper.
- [ ] SQLAlchemy models use `BaseTable`; mappers registered once.
- [ ] Frontend follows FSD layer boundaries.
- [ ] Room entity exports through `index.ts` barrel.
- [ ] Mutations invalidate/set query data consistently.
- [ ] Forms use HeroUI accessible primitives and visible errors.
- [ ] No hardcoded real secrets.
- [ ] No unnecessary scope additions.
- [ ] Self-contained — no questions needed during implementation.

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Guest participant conflicts with existing login-based `ExamService` | High | High | Create room-specific participant/session usecase; reuse payload shapes, not `CurrentUser` assumptions |
| “방=시험” has fewer fields than existing exam generation requires | High | Medium | First PR creates/join/admin shell; session bridge uses defaults or defers full generation settings to follow-up. Document defaults clearly. |
| Participant token storage in frontend is weaker than HttpOnly auth | Medium | Medium | Prefer HttpOnly cookie; if sessionStorage used for capstone MVP, keep token short-lived and document limitation |
| Room/session duplication with existing exam domain | Medium | High | Mirror existing exam contracts and factor shared service only after behavior is stable |
| UI route is public and may accidentally use viewer auth redirects | Medium | Medium | Keep `/rooms/*` outside `student`/`professor` layouts; do not call `useViewer` in join flow |
| Migration touches shared backend DB | Medium | High | Add focused migration tests and review autogenerate output manually |

## Notes
- Current manyfast policy was updated: spec `S-SNAUBV` now describes URL + student name + room password participation and admin password room management.
- This plan intentionally treats room as a separate MVP surface because existing `ExamService` is role- and classroom-membership-based (`current_user.role == STUDENT`, `classroom_usecase.get_classroom(...)`). Forcing guest room participants through that service would create authorization shortcuts.
- CLI reusable concepts are `ExamConfig`, question/follow-up/result contracts, and `ExamSessionState`; Web implementation should reuse or mirror these contracts rather than copying terminal input loops.
