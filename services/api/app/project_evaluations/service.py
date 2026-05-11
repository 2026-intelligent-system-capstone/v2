from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import Counter
from collections.abc import Callable

from fastapi import HTTPException, UploadFile, status

from services.api.app.project_evaluations.rag.redaction import redact_sensitive_text

from services.api.app.project_evaluations.analysis.context_builder import (
    build_project_context,
)
from services.api.app.project_evaluations.analysis.llm_client import LlmClient
from services.api.app.project_evaluations.domain.models import (
    ArtifactUploadResult,
    AdminVerifyRead,
    ArtifactStatus,
    EvaluationReportRead,
    EvaluationStatus,
    ExtractedProjectContextRead,
    InterviewQuestionRead,
    InterviewSessionRead,
    InterviewTurnCreate,
    InterviewTurnRead,
    JoinEvaluationRead,
    ProjectArtifactRead,
    ProjectEvaluationCreate,
    ProjectEvaluationRead,
)
from services.api.app.project_evaluations.ingestion.file_classifier import (
    CODE_EXTENSIONS,
    DOCUMENT_EXTENSIONS,
)
from services.api.app.project_evaluations.ingestion.zip_handler import (
    extract_zip_artifacts,
)
from services.api.app.project_evaluations.interview.evaluator import evaluate_answer
from services.api.app.project_evaluations.interview.question_generator import (
    generate_questions,
)
from services.api.app.project_evaluations.reports.report_generator import (
    generate_report_payload,
)
from services.api.app.project_evaluations.persistence.repository import (
    ProjectEvaluationRepository,
    from_json,
)
from services.api.app.settings import ApiSettings

PASSWORD_HASH_ITERATIONS = 120_000
AUTH_WINDOW_SECONDS = 60
AUTH_MAX_FAILURES = 8
_AUTH_FAILURES: dict[tuple[str, str, str], list[float]] = {}


def _safe_error_message(exc: Exception, prefix: str) -> str:
    detail = redact_sensitive_text(" ".join(str(exc).split()))[:240]
    return f"{prefix} 원인: {detail}" if detail else prefix


def _stage_error_detail(stage: str, message: str, exc: Exception, **context: object) -> dict[str, object]:
    detail: dict[str, object] = {
        "stage": stage,
        "error_type": type(exc).__name__,
        "message": _safe_error_message(exc, message),
    }
    return {**detail, **{key: value for key, value in context.items() if value not in (None, "", {})}}


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PASSWORD_HASH_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt}${digest}"


def _new_session_token() -> str:
    return secrets.token_urlsafe(32)


def _rate_limit_key(scope: str, evaluation_id: str, identity: str) -> tuple[str, str, str]:
    return (scope, evaluation_id, identity or "anonymous")


def _check_auth_attempt(scope: str, evaluation_id: str, identity: str) -> None:
    now = time.monotonic()
    key = _rate_limit_key(scope, evaluation_id, identity)
    attempts = [t for t in _AUTH_FAILURES.get(key, []) if now - t < AUTH_WINDOW_SECONDS]
    _AUTH_FAILURES[key] = attempts
    if len(attempts) >= AUTH_MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="인증 시도가 너무 많습니다. 잠시 후 다시 시도하세요.",
        )


def _record_auth_failure(scope: str, evaluation_id: str, identity: str) -> None:
    key = _rate_limit_key(scope, evaluation_id, identity)
    _AUTH_FAILURES.setdefault(key, []).append(time.monotonic())


def _clear_auth_failures(scope: str, evaluation_id: str, identity: str) -> None:
    _AUTH_FAILURES.pop(_rate_limit_key(scope, evaluation_id, identity), None)


def _verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)
        ).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


class ProjectEvaluationService:
    def __init__(
        self, repository: ProjectEvaluationRepository, settings: ApiSettings
    ) -> None:
        self.repository = repository
        self.settings = settings
        self._analysis_llm = LlmClient(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_ANALYSIS_MODEL,
        )
        self._question_llm = LlmClient(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_QUESTION_MODEL,
        )
        self._eval_llm = LlmClient(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_EVAL_MODEL,
        )
        self._report_llm = LlmClient(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_EVAL_MODEL,
        )
        self._openai = None
        self._qdrant = None
        if settings.RAG_ENABLED and settings.OPENAI_API_KEY:
            from openai import OpenAI

            self._openai = OpenAI(api_key=settings.OPENAI_API_KEY)
        if settings.RAG_ENABLED and settings.QDRANT_URL and self._openai is not None:
            from qdrant_client import QdrantClient

            self._qdrant = QdrantClient(url=settings.QDRANT_URL)

    def create_evaluation(
        self, payload: ProjectEvaluationCreate
    ) -> ProjectEvaluationRead:
        if not payload.room_password.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="방 비밀번호를 입력하세요.",
            )
        if not payload.admin_password.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="관리자 비밀번호를 입력하세요.",
            )
        if sum(payload.question_policy.bloom_ratios.values()) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bloom 비율은 하나 이상 1 이상이어야 합니다.",
            )
        return self.repository.create_evaluation(
            payload,
            room_password_hash=_hash_password(payload.room_password),
            admin_password_hash=_hash_password(payload.admin_password),
        )

    def get_evaluation(self, evaluation_id: str) -> ProjectEvaluationRead:
        evaluation = self.repository.get_evaluation(evaluation_id)
        if evaluation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="프로젝트 평가를 찾을 수 없습니다.",
            )
        return evaluation

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
            self.repository.create_artifact(
                evaluation_id=evaluation_id,
                source_path=item.source_path,
                source_type=item.source_type,
                status=item.status,
                raw_text=item.raw_text,
                metadata=item.metadata,
            )
            for item in extracted
        ]
        self.repository.update_evaluation_status(
            evaluation_id, EvaluationStatus.UPLOADED
        )
        accepted_count = sum(1 for item in artifacts if item.status == ArtifactStatus.EXTRACTED)
        reason_counts = Counter(
            str(item.metadata.get("reason", "accepted"))
            if item.status != ArtifactStatus.EXTRACTED
            else "accepted"
            for item in artifacts
        )
        return ArtifactUploadResult(
            evaluation_id=evaluation_id,
            accepted_count=accepted_count,
            skipped_count=len(artifacts) - accepted_count,
            ignored_count=reason_counts.get("ignored", 0)
            + reason_counts.get("ignored_path", 0)
            + reason_counts.get("unsupported_extension", 0),
            empty_text_count=reason_counts.get("empty_text", 0),
            file_too_large_count=reason_counts.get("file_too_large", 0),
            processed_file_limit_count=reason_counts.get("processed_file_limit", 0),
            failed_count=sum(1 for item in artifacts if item.status == ArtifactStatus.FAILED),
            reason_counts=dict(reason_counts),
            processing_limits=self._processing_limits(),
            supported_extensions=self._supported_extensions(),
            artifacts=artifacts,
        )

    def _processing_limits(self) -> dict[str, int]:
        return {
            "max_zip_bytes": self.settings.APP_MAX_UPLOAD_MB * 1024 * 1024,
            "max_file_bytes": self.settings.APP_MAX_TEXT_FILE_MB * 1024 * 1024,
            "max_files": self.settings.APP_MAX_PROCESSED_FILES,
        }

    def _supported_extensions(self) -> list[str]:
        return sorted(DOCUMENT_EXTENSIONS | CODE_EXTENSIONS)

    def list_artifacts(self, evaluation_id: str) -> list[ProjectArtifactRead]:
        self.get_evaluation(evaluation_id)
        return self.repository.list_artifacts(evaluation_id)

    def extract_context(self, evaluation_id: str) -> ExtractedProjectContextRead:
        self.get_evaluation(evaluation_id)
        if self.repository.has_sessions(evaluation_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="인터뷰가 시작된 평가는 다시 분석할 수 없습니다.",
            )
        artifacts = self.repository.list_artifact_rows(evaluation_id)
        rag_status = self._build_rag_status(evaluation_id, artifacts)
        try:
            context = build_project_context(artifacts, llm=self._analysis_llm)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=_stage_error_detail(
                    "context_extraction",
                    "AI 프로젝트 분석 실패: LLM context 생성 중 오류가 발생했습니다.",
                    exc,
                    llm_model=self.settings.OPENAI_ANALYSIS_MODEL,
                    rag_status=rag_status,
                ),
            ) from exc
        saved = self.repository.save_context(
            evaluation_id=evaluation_id,
            summary=str(context["summary"]),
            tech_stack=list(context["tech_stack"]),
            features=list(context["features"]),
            architecture_notes=list(context["architecture_notes"]),
            data_flow=list(context["data_flow"]),
            risk_points=list(context["risk_points"]),
            question_targets=list(context["question_targets"]),
            areas=list(context["areas"]),
            rag_status=rag_status,
        )
        self.repository.update_evaluation_status(
            evaluation_id, EvaluationStatus.ANALYZED
        )
        return saved

    def _build_rag_status(self, evaluation_id: str, artifacts: list) -> dict[str, object]:
        if not self.settings.RAG_ENABLED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "stage": "rag_ingestion",
                    "reason": "rag_disabled",
                    "message": "질문 생성에는 RAG 인덱싱이 필요합니다. RAG_ENABLED 설정을 확인하세요.",
                },
            )
        try:
            result = self._ingest_rag(evaluation_id, artifacts)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=_stage_error_detail(
                    "rag_ingestion",
                    "RAG 인덱싱 중 외부 의존성 또는 벡터 저장소 오류가 발생했습니다.",
                    exc,
                    collection_name=self.settings.QDRANT_COLLECTION_NAME,
                    embedding_model=self.settings.OPENAI_EMBEDDING_MODEL,
                ),
            ) from exc
        return {
            "enabled": True,
            "status": "indexed",
            "inserted_count": result.inserted_count,
            "code_chunk_count": result.code_chunk_count,
            "document_chunk_count": result.document_chunk_count,
            "manifest_chunk_count": result.manifest_chunk_count,
            "skipped_count": result.skipped_count,
            "collection_name": self.settings.QDRANT_COLLECTION_NAME,
            "embedding_model": self.settings.OPENAI_EMBEDDING_MODEL,
        }

    def _ingest_rag(self, evaluation_id: str, artifacts: list):
        if self._openai is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="RAG 인덱싱에 필요한 OpenAI client가 초기화되지 않았습니다. OPENAI_API_KEY를 확인하세요.",
            )
        if self._qdrant is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="RAG 인덱싱에 필요한 Qdrant client가 초기화되지 않았습니다. QDRANT_URL을 확인하세요.",
            )
        from services.api.app.project_evaluations.rag.embedder import ingest_evaluation

        result = ingest_evaluation(
            evaluation_id=evaluation_id,
            artifacts=artifacts,
            openai_client=self._openai,
            qdrant_client=self._qdrant,
            collection_name=self.settings.QDRANT_COLLECTION_NAME,
            embedding_model=self.settings.OPENAI_EMBEDDING_MODEL,
        )
        if result.inserted_count == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="RAG 인덱싱 결과 저장된 chunk가 없습니다. zip 내부 파일 형식, 텍스트 추출 결과, artifact role 분류를 확인하세요.",
            )
        return result

    def _make_retriever(self, evaluation_id: str) -> Callable[..., list] | None:
        if self._qdrant is None or self._openai is None:
            return None
        openai_client = self._openai
        qdrant_client = self._qdrant
        collection_name = self.settings.QDRANT_COLLECTION_NAME
        embedding_model = self.settings.OPENAI_EMBEDDING_MODEL

        def retriever(query: str, **kwargs: object) -> list:
            from services.api.app.project_evaluations.rag.retriever import retrieve_chunks

            return retrieve_chunks(
                query=query,
                evaluation_id=evaluation_id,
                openai_client=openai_client,
                qdrant_client=qdrant_client,
                collection_name=collection_name,
                embedding_model=embedding_model,
                artifact_roles=kwargs.get("artifact_roles"),
                chunk_types=kwargs.get("chunk_types"),
                source_types=kwargs.get("source_types"),
                top_k=int(kwargs.get("top_k", 5)),
            )

        return retriever

    def get_context(self, evaluation_id: str) -> ExtractedProjectContextRead:
        self.get_evaluation(evaluation_id)
        context = self.repository.get_context(evaluation_id)
        if context is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="아직 프로젝트 context가 생성되지 않았습니다.",
            )
        return context

    def generate_questions(self, evaluation_id: str) -> list[InterviewQuestionRead]:
        self.get_context(evaluation_id)
        if self.repository.has_sessions(evaluation_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="인터뷰가 시작된 평가는 질문을 다시 생성할 수 없습니다.",
            )
        context_row = self.repository.get_context_row(evaluation_id)
        if context_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="아직 프로젝트 context가 생성되지 않았습니다.",
            )
        if self.settings.RAG_ENABLED:
            self._ensure_rag_ready(context_row)
        artifact_rows = self.repository.list_artifact_rows(evaluation_id)
        area_rows = self.repository.list_area_rows(evaluation_id)
        question_policy = self.repository.get_question_policy(evaluation_id)
        retriever = self._make_retriever(evaluation_id) if self.settings.RAG_ENABLED else None
        try:
            questions = generate_questions(
                evaluation_id,
                area_rows,
                context=context_row,
                artifacts=artifact_rows,
                llm=self._question_llm,
                retriever=retriever,
                require_rag=self.settings.RAG_ENABLED,
                question_policy=question_policy,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=_stage_error_detail(
                    "question_generation",
                    "AI 질문 생성 실패: LLM 또는 RAG 검색 처리 중 오류가 발생했습니다.",
                    exc,
                    llm_model=self.settings.OPENAI_QUESTION_MODEL,
                    rag_status=from_json(context_row.rag_status_json, {}),
                ),
            ) from exc
        saved = self.repository.save_questions(evaluation_id, questions)
        self.repository.update_evaluation_status(
            evaluation_id, EvaluationStatus.QUESTIONS_GENERATED
        )
        return saved

    def _ensure_rag_ready(self, context_row) -> None:
        from services.api.app.project_evaluations.persistence.repository import from_json

        rag_status = from_json(context_row.rag_status_json, {})
        if rag_status.get("status") == "indexed":
            return
        if rag_status.get("status") == "failed":
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "stage": "question_generation",
                    "reason": "rag_ingestion_failed",
                    "message": "질문 생성 실패: RAG 인덱싱이 실패했습니다.",
                    "rag_status": rag_status,
                },
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "stage": "question_generation",
                "reason": "rag_not_ready",
                "message": "질문 생성 실패: RAG 인덱스가 준비되지 않았습니다. 먼저 프로젝트 분석을 완료하세요.",
                "rag_status": rag_status,
            },
        )

    def list_questions(self, evaluation_id: str) -> list[InterviewQuestionRead]:
        self.get_evaluation(evaluation_id)
        return self.repository.list_questions(evaluation_id)

    def verify_admin(
        self, evaluation_id: str, admin_password: str, client_id: str = "local"
    ) -> AdminVerifyRead:
        self.ensure_admin(evaluation_id, admin_password, client_id)
        return AdminVerifyRead(ok=True)

    def ensure_admin(
        self, evaluation_id: str, admin_password: str | None, client_id: str = "local"
    ) -> None:
        row = self.repository.get_evaluation_row(evaluation_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="프로젝트 평가를 찾을 수 없습니다.",
            )
        _check_auth_attempt("admin", evaluation_id, client_id)
        if not admin_password or not row.admin_password_hash or not _verify_password(
            admin_password, row.admin_password_hash
        ):
            _record_auth_failure("admin", evaluation_id, client_id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="관리자 비밀번호가 올바르지 않습니다.",
            )
        _clear_auth_failures("admin", evaluation_id, client_id)

    def join_evaluation(
        self,
        evaluation_id: str,
        participant_name: str,
        room_password: str,
        client_id: str = "local",
    ) -> JoinEvaluationRead:
        row = self.repository.get_evaluation_row(evaluation_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="프로젝트 평가를 찾을 수 없습니다.",
            )
        _check_auth_attempt("room", evaluation_id, client_id)
        if not row.room_password_hash or not _verify_password(
            room_password, row.room_password_hash
        ):
            _record_auth_failure("room", evaluation_id, client_id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="방 비밀번호가 올바르지 않습니다.",
            )
        _clear_auth_failures("room", evaluation_id, client_id)
        if not self.repository.list_question_rows(evaluation_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="아직 입장 가능한 인터뷰 질문이 생성되지 않았습니다.",
            )
        session = self._create_session(evaluation_id, participant_name.strip())
        evaluation = self.get_evaluation(evaluation_id)
        return JoinEvaluationRead(
            evaluation=evaluation,
            session=session,
            interview_url_path=f"/interview/{evaluation_id}/{session.id}/open",
        )

    def create_session(
        self,
        evaluation_id: str,
        participant_name: str = "",
        admin_password: str | None = None,
        client_id: str = "local",
    ) -> InterviewSessionRead:
        self.ensure_admin(evaluation_id, admin_password, client_id)
        return self._create_session(evaluation_id, participant_name)

    def _create_session(
        self, evaluation_id: str, participant_name: str = ""
    ) -> InterviewSessionRead:
        self.get_evaluation(evaluation_id)
        if not self.repository.list_question_rows(evaluation_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="인터뷰를 시작하기 전에 질문을 먼저 생성해야 합니다.",
            )
        session_token = _new_session_token()
        session = self.repository.create_session(
            evaluation_id,
            participant_name,
            session_token_hash=_hash_password(session_token),
            session_token=session_token,
        )
        self.repository.update_evaluation_status(
            evaluation_id, EvaluationStatus.INTERVIEWING
        )
        return session

    def submit_turn(
        self,
        evaluation_id: str,
        session_id: str,
        payload: InterviewTurnCreate,
        session_token: str | None = None,
        client_id: str = "local",
    ) -> InterviewTurnRead:
        session = self.ensure_session(evaluation_id, session_id, session_token, client_id)
        question = self.repository.get_question_row(payload.question_id)
        if question is None or question.evaluation_id != evaluation_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="질문을 찾을 수 없습니다.",
            )
        if session.status.value == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="이미 완료된 인터뷰입니다.",
            )
        if question.order_index != session.current_question_index:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="현재 순서의 질문에만 답변할 수 있습니다.",
            )
        if self.repository.has_turn_for_question(session_id, payload.question_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="이미 답변한 질문입니다.",
            )
        try:
            evaluation = evaluate_answer(question, payload.answer_text, llm=self._eval_llm)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=_stage_error_detail(
                    "answer_evaluation",
                    "AI 답변 평가 실패: LLM 평가 처리 중 오류가 발생했습니다.",
                    exc,
                    llm_model=self.settings.OPENAI_EVAL_MODEL,
                    question_id=payload.question_id,
                ),
            ) from exc
        return self.repository.create_turn(
            session_id=session_id,
            question=question,
            answer_text=payload.answer_text,
            score=float(evaluation["score"]),
            evaluation_summary=str(evaluation["evaluation_summary"]),
            rubric_scores=list(evaluation["rubric_scores"]),
            evidence_matches=list(evaluation["evidence_matches"]),
            evidence_mismatches=list(evaluation["evidence_mismatches"]),
            suspicious_points=list(evaluation["suspicious_points"]),
            strengths=list(evaluation["strengths"]),
            follow_up_question=evaluation["follow_up_question"],
        )

    def list_turns(
        self,
        evaluation_id: str,
        session_id: str,
        session_token: str | None = None,
        client_id: str = "local",
    ) -> list[InterviewTurnRead]:
        self.ensure_session(evaluation_id, session_id, session_token, client_id)
        return self.repository.list_turns(session_id)

    def complete_session(
        self,
        evaluation_id: str,
        session_id: str,
        session_token: str | None = None,
        client_id: str = "local",
    ) -> EvaluationReportRead:
        session = self.ensure_session(evaluation_id, session_id, session_token, client_id)
        if session.status.value == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="이미 완료된 인터뷰입니다.",
            )
        questions = self.repository.list_question_rows(evaluation_id)
        turns = self.repository.list_turn_rows(session_id)
        if len(turns) < len(questions):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="모든 질문에 답변한 뒤 인터뷰를 완료할 수 있습니다.",
            )
        areas = self.repository.list_area_rows(evaluation_id)
        rubric_scores_by_turn = self.repository.rubric_scores_by_turn([turn.id for turn in turns])
        try:
            report = generate_report_payload(
                areas,
                questions,
                turns,
                llm=self._report_llm,
                rubric_scores_by_turn=rubric_scores_by_turn,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=_stage_error_detail(
                    "report_generation",
                    "AI 최종 리포트 생성 실패: LLM 리포트 작성 중 오류가 발생했습니다.",
                    exc,
                    llm_model=self.settings.OPENAI_EVAL_MODEL,
                ),
            ) from exc
        return self.repository.save_completed_report(
            evaluation_id=evaluation_id,
            session_id=session_id,
            final_decision=report["final_decision"],
            authenticity_score=float(report["authenticity_score"]),
            summary=str(report["summary"]),
            area_analyses=list(report["area_analyses"]),
            question_evaluations=list(report["question_evaluations"]),
            bloom_summary=dict(report["bloom_summary"]),
            rubric_summary=dict(report["rubric_summary"]),
            evidence_alignment=list(report["evidence_alignment"]),
            strengths=list(report["strengths"]),
            suspicious_points=list(report["suspicious_points"]),
            recommended_followups=list(report["recommended_followups"]),
        )

    def get_latest_report(self, evaluation_id: str) -> EvaluationReportRead:
        self.get_evaluation(evaluation_id)
        report = self.repository.get_latest_report(evaluation_id)
        if report is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="아직 생성된 리포트가 없습니다.",
            )
        return report

    def get_report(self, evaluation_id: str, report_id: str) -> EvaluationReportRead:
        self.get_evaluation(evaluation_id)
        report = self.repository.get_report(report_id)
        if report is None or report.evaluation_id != evaluation_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="리포트를 찾을 수 없습니다.",
            )
        return report

    def ensure_session(
        self,
        evaluation_id: str,
        session_id: str,
        session_token: str | None = None,
        client_id: str = "local",
    ) -> InterviewSessionRead:
        session_row = self.repository.get_session_row(session_id)
        if session_row is None or session_row.evaluation_id != evaluation_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="인터뷰 세션을 찾을 수 없습니다.",
            )
        if not session_row.session_token_hash:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="인터뷰 세션 토큰이 설정되지 않은 기존 세션입니다. 새로 입장하세요.",
            )
        _check_auth_attempt("session", evaluation_id, f"{session_id}:{client_id}")
        if not _verify_password(session_token or "", session_row.session_token_hash):
            _record_auth_failure("session", evaluation_id, f"{session_id}:{client_id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="인터뷰 세션 토큰이 올바르지 않습니다.",
            )
        _clear_auth_failures("session", evaluation_id, f"{session_id}:{client_id}")
        return self.repository.to_session_read(session_row)

    def submit_turns_bulk(
        self,
        evaluation_id: str,
        session_id: str,
        answer_texts: list[str],
        session_token: str | None = None,
        client_id: str = "local",
    ) -> EvaluationReportRead:
        """Submit all voice interview answers at once and generate report.

        Maps answer_texts[i] → questions[i] by order_index.
        Used by the Realtime API proxy after interview ends.
        """
        questions = self.repository.list_question_rows(evaluation_id)
        if not questions:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "stage": "answer_evaluation",
                    "reason": "questions_not_generated",
                    "message": "일괄 답변 평가 전에 인터뷰 질문을 먼저 생성해야 합니다.",
                },
            )
        if len(answer_texts) != len(questions):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "stage": "answer_evaluation",
                    "reason": "answer_count_mismatch",
                    "message": "일괄 답변 수가 질문 수와 일치하지 않습니다.",
                    "question_count": len(questions),
                    "answer_count": len(answer_texts),
                },
            )
        for i in range(len(questions)):
            text = answer_texts[i].strip() or "(답변 없음)"
            payload = InterviewTurnCreate(
                question_id=questions[i].id,
                answer_text=text,
            )
            self.submit_turn(evaluation_id, session_id, payload, session_token, client_id)
        return self.complete_session(evaluation_id, session_id, session_token, client_id)
