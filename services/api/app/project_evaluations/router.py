from collections.abc import Generator
import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile, status
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
    InterviewTranscriptionRead,
    InterviewTurnCreate,
    InterviewTurnFlowRequest,
    InterviewTurnFlowResponse,
    InterviewTurnMode,
    InterviewTurnRead,
    JoinEvaluationRead,
    JoinEvaluationRequest,
    ProjectArtifactRead,
    ProjectEvaluationCreate,
    ProjectEvaluationRead,
    ProjectEvaluationStatusRead,
    StudentInterviewStateRead,
)
from services.api.app.project_evaluations.interview.speech_service import (
    SUPPORTED_AUDIO_EXTENSIONS,
    SpeechService,
)
from services.api.app.project_evaluations.interview.turn_flow import InterviewTurnFlow
from services.api.app.project_evaluations.persistence.repository import (
    ProjectEvaluationRepository,
)
from services.api.app.project_evaluations.service import ProjectEvaluationService

router = APIRouter(prefix="/api/project-evaluations", tags=["project-evaluations"])


def _safe_upload_filename(filename: str) -> str:
    basename = Path(filename or "audio").name
    safe = "".join(char for char in basename if char.isprintable() and char not in "\\/")
    return safe[:120] or "audio"


async def _read_limited_upload(file: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={
                    "stage": "audio_transcription",
                    "reason": "audio_too_large",
                    "message": "오디오 파일이 허용 크기를 초과했습니다.",
                    "max_bytes": max_bytes,
                    "actual_bytes": total,
                },
            )
        chunks.append(chunk)
    return b"".join(chunks)


def get_db_session(request: Request) -> Generator[Session, None, None]:
    yield from get_session(request.app.state.session_factory)


def client_id(request: Request) -> str:
    return request.client.host if request.client else "local"


def interview_session_token(
    request: Request,
    session_id: str,
    x_session_token: Annotated[str | None, Header()] = None,
) -> str | None:
    return x_session_token or request.cookies.get(f"interview_session_{session_id}")


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


@router.get("/{evaluation_id}/status", response_model=ProjectEvaluationStatusRead)
def get_evaluation_status(
    evaluation_id: str,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    x_admin_password: Annotated[str | None, Header()] = None,
) -> ProjectEvaluationStatusRead:
    service.ensure_admin(evaluation_id, x_admin_password)
    return service.get_status(evaluation_id)


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


@router.get(
    "/{evaluation_id}/sessions/{session_id}/interview/state",
    response_model=StudentInterviewStateRead,
)
def get_interview_state(
    evaluation_id: str,
    session_id: str,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    request_client_id: Annotated[str, Depends(client_id)],
    session_token: Annotated[str | None, Depends(interview_session_token)],
) -> StudentInterviewStateRead:
    return InterviewTurnFlow(service).get_state(
        evaluation_id, session_id, session_token, request_client_id
    )


@router.post(
    "/{evaluation_id}/sessions/{session_id}/interview/transcribe",
    response_model=InterviewTranscriptionRead,
)
async def transcribe_interview_audio(
    evaluation_id: str,
    session_id: str,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    request_client_id: Annotated[str, Depends(client_id)],
    session_token: Annotated[str | None, Depends(interview_session_token)],
    mode: Annotated[InterviewTurnMode, Form()] = InterviewTurnMode.ANSWER,
    audio: UploadFile = File(...),
) -> InterviewTranscriptionRead:
    service.ensure_session(evaluation_id, session_id, session_token, request_client_id)
    filename = _safe_upload_filename(audio.filename or "audio")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "stage": "audio_transcription",
                "reason": "unsupported_audio_format",
                "message": "지원하지 않는 오디오 형식입니다.",
                "filename": filename,
                "supported_extensions": sorted(SUPPORTED_AUDIO_EXTENSIONS),
            },
        )
    max_bytes = service.settings.OPENAI_AUDIO_MAX_UPLOAD_MB * 1024 * 1024
    content = await _read_limited_upload(audio, max_bytes)
    try:
        speech_service = SpeechService(service.settings)
        transcript = await asyncio.to_thread(
            speech_service.transcribe_audio,
            content,
            filename,
            audio.content_type,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "stage": "audio_transcription",
                "model": service.settings.OPENAI_TRANSCRIBE_MODEL,
                "filename": filename,
                "content_type": audio.content_type,
                "message": "오디오 전사 실패: STT 처리 중 오류가 발생했습니다.",
            },
        ) from exc
    return InterviewTranscriptionRead(transcript=transcript, mode=mode)


@router.post(
    "/{evaluation_id}/sessions/{session_id}/interview/answer",
    response_model=InterviewTurnFlowResponse,
)
def submit_interview_answer(
    evaluation_id: str,
    session_id: str,
    payload: InterviewTurnFlowRequest,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    request_client_id: Annotated[str, Depends(client_id)],
    session_token: Annotated[str | None, Depends(interview_session_token)],
) -> InterviewTurnFlowResponse:
    return InterviewTurnFlow(service).submit_answer(
        evaluation_id, session_id, payload, session_token, request_client_id
    )


@router.post(
    "/{evaluation_id}/sessions/{session_id}/interview/complete",
    response_model=EvaluationReportRead,
)
def complete_interview(
    evaluation_id: str,
    session_id: str,
    service: Annotated[ProjectEvaluationService, Depends(get_service)],
    request_client_id: Annotated[str, Depends(client_id)],
    session_token: Annotated[str | None, Depends(interview_session_token)],
) -> EvaluationReportRead:
    return service.complete_session(evaluation_id, session_id, session_token, request_client_id)


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
