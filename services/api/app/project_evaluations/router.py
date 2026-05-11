from collections.abc import Generator
from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, Request, UploadFile
from sqlalchemy.orm import Session

from services.api.app.database import get_session
from services.api.app.project_evaluations.domain.models import (
    AdminVerifyRead,
    AdminVerifyRequest,
    ArtifactUploadResult,
    EvaluationReportRead,
    ExtractedProjectContextRead,
    InterviewQuestionRead,
    InterviewSessionRead,
    InterviewTurnCreate,
    InterviewTurnRead,
    JoinEvaluationRead,
    JoinEvaluationRequest,
    ProjectArtifactRead,
    ProjectEvaluationCreate,
    ProjectEvaluationRead,
)
from services.api.app.project_evaluations.persistence.repository import (
    ProjectEvaluationRepository,
)
from services.api.app.project_evaluations.service import ProjectEvaluationService

router = APIRouter(prefix="/api/project-evaluations", tags=["project-evaluations"])


def get_db_session(request: Request) -> Generator[Session, None, None]:
    yield from get_session(request.app.state.session_factory)


def client_id(request: Request) -> str:
    return request.client.host if request.client else "local"


def get_service(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEvaluationService:
    return ProjectEvaluationService(
        ProjectEvaluationRepository(session),
        request.app.state.settings,
    )


@router.post("", response_model=ProjectEvaluationRead)
def create_evaluation(
    payload: ProjectEvaluationCreate,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
) -> ProjectEvaluationRead:
    return service.create_evaluation(payload)


@router.get("/{evaluation_id}", response_model=ProjectEvaluationRead)
def get_evaluation(
    evaluation_id: str,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    x_admin_password: Annotated[str | None, Header()] = None,
) -> ProjectEvaluationRead:
    service.ensure_admin(evaluation_id, x_admin_password)
    return service.get_evaluation(evaluation_id)


@router.post("/{evaluation_id}/admin/verify", response_model=AdminVerifyRead)
def verify_admin(
    evaluation_id: str,
    payload: AdminVerifyRequest,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    request_client_id: Annotated[str, Depends(client_id)],
) -> AdminVerifyRead:
    return service.verify_admin(evaluation_id, payload.admin_password, request_client_id)


@router.post("/{evaluation_id}/join", response_model=JoinEvaluationRead)
def join_evaluation(
    evaluation_id: str,
    payload: JoinEvaluationRequest,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    request_client_id: Annotated[str, Depends(client_id)],
) -> JoinEvaluationRead:
    return service.join_evaluation(
        evaluation_id, payload.participant_name, payload.room_password, request_client_id
    )


@router.post("/{evaluation_id}/artifacts/zip", response_model=ArtifactUploadResult)
async def upload_zip_artifact(
    evaluation_id: str,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    file: UploadFile = File(...),
    x_admin_password: Annotated[str | None, Header()] = None,
) -> ArtifactUploadResult:
    service.ensure_admin(evaluation_id, x_admin_password)
    return await service.upload_zip(evaluation_id, file)


@router.get("/{evaluation_id}/artifacts", response_model=list[ProjectArtifactRead])
def list_artifacts(
    evaluation_id: str,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    x_admin_password: Annotated[str | None, Header()] = None,
) -> list[ProjectArtifactRead]:
    service.ensure_admin(evaluation_id, x_admin_password)
    return service.list_artifacts(evaluation_id)


@router.post("/{evaluation_id}/extract", response_model=ExtractedProjectContextRead)
def extract_context(
    evaluation_id: str,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    x_admin_password: Annotated[str | None, Header()] = None,
) -> ExtractedProjectContextRead:
    service.ensure_admin(evaluation_id, x_admin_password)
    return service.extract_context(evaluation_id)


@router.get("/{evaluation_id}/context", response_model=ExtractedProjectContextRead)
def get_context(
    evaluation_id: str,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    x_admin_password: Annotated[str | None, Header()] = None,
) -> ExtractedProjectContextRead:
    service.ensure_admin(evaluation_id, x_admin_password)
    return service.get_context(evaluation_id)


@router.post(
    "/{evaluation_id}/questions/generate", response_model=list[InterviewQuestionRead]
)
def generate_questions(
    evaluation_id: str,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    x_admin_password: Annotated[str | None, Header()] = None,
) -> list[InterviewQuestionRead]:
    service.ensure_admin(evaluation_id, x_admin_password)
    return service.generate_questions(evaluation_id)


@router.get("/{evaluation_id}/questions", response_model=list[InterviewQuestionRead])
def list_questions(
    evaluation_id: str,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    x_admin_password: Annotated[str | None, Header()] = None,
) -> list[InterviewQuestionRead]:
    service.ensure_admin(evaluation_id, x_admin_password)
    return service.list_questions(evaluation_id)


@router.post("/{evaluation_id}/sessions", response_model=InterviewSessionRead)
def create_session(
    evaluation_id: str,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    x_admin_password: Annotated[str | None, Header()] = None,
) -> InterviewSessionRead:
    return service.create_session(evaluation_id, admin_password=x_admin_password)


@router.post(
    "/{evaluation_id}/sessions/{session_id}/turns", response_model=InterviewTurnRead
)
def submit_turn(
    evaluation_id: str,
    session_id: str,
    payload: InterviewTurnCreate,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    request_client_id: Annotated[str, Depends(client_id)],
    x_session_token: Annotated[str | None, Header()] = None,
) -> InterviewTurnRead:
    return service.submit_turn(
        evaluation_id, session_id, payload, x_session_token, request_client_id
    )


@router.get(
    "/{evaluation_id}/sessions/{session_id}/turns",
    response_model=list[InterviewTurnRead],
)
def list_turns(
    evaluation_id: str,
    session_id: str,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    request_client_id: Annotated[str, Depends(client_id)],
    x_session_token: Annotated[str | None, Header()] = None,
) -> list[InterviewTurnRead]:
    return service.list_turns(evaluation_id, session_id, x_session_token, request_client_id)


@router.post(
    "/{evaluation_id}/sessions/{session_id}/complete",
    response_model=EvaluationReportRead,
)
def complete_session(
    evaluation_id: str,
    session_id: str,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    request_client_id: Annotated[str, Depends(client_id)],
    x_session_token: Annotated[str | None, Header()] = None,
) -> EvaluationReportRead:
    return service.complete_session(evaluation_id, session_id, x_session_token, request_client_id)


@router.get("/{evaluation_id}/reports/latest", response_model=EvaluationReportRead)
def get_latest_report(
    evaluation_id: str,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    x_admin_password: Annotated[str | None, Header()] = None,
) -> EvaluationReportRead:
    service.ensure_admin(evaluation_id, x_admin_password)
    return service.get_latest_report(evaluation_id)


@router.get("/{evaluation_id}/reports/{report_id}", response_model=EvaluationReportRead)
def get_report(
    evaluation_id: str,
    report_id: str,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    x_admin_password: Annotated[str | None, Header()] = None,
) -> EvaluationReportRead:
    service.ensure_admin(evaluation_id, x_admin_password)
    return service.get_report(evaluation_id, report_id)
