from __future__ import annotations

import hashlib
import hmac
import secrets
from collections import Counter
from collections.abc import Callable

from fastapi import HTTPException, UploadFile, status

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
)
from services.api.app.settings import ApiSettings

PASSWORD_HASH_ITERATIONS = 120_000


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PASSWORD_HASH_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt}${digest}"


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
        self._openai = None
        self._qdrant = None
        if settings.OPENAI_API_KEY:
            try:
                from openai import OpenAI
                self._openai = OpenAI(api_key=settings.OPENAI_API_KEY)
            except Exception:
                pass
        if settings.QDRANT_URL and self._openai is not None:
            try:
                from qdrant_client import QdrantClient
                self._qdrant = QdrantClient(url=settings.QDRANT_URL)
            except Exception:
                pass

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
            ignored_count=reason_counts.get("ignored", 0),
            empty_text_count=reason_counts.get("empty_text", 0),
            file_too_large_count=reason_counts.get("file_too_large", 0),
            processed_file_limit_count=reason_counts.get("processed_file_limit", 0),
            failed_count=sum(1 for item in artifacts if item.status == ArtifactStatus.FAILED),
            reason_counts=dict(reason_counts),
            artifacts=artifacts,
        )

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
        context = build_project_context(artifacts, llm=self._analysis_llm)
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
        )
        self.repository.update_evaluation_status(
            evaluation_id, EvaluationStatus.ANALYZED
        )
        self._try_ingest_rag(evaluation_id, artifacts)
        return saved

    def _try_ingest_rag(self, evaluation_id: str, artifacts: list) -> None:
        if self._qdrant is None or self._openai is None:
            return
        try:
            from services.api.app.project_evaluations.rag.embedder import ingest_evaluation
            ingest_evaluation(
                evaluation_id=evaluation_id,
                artifacts=artifacts,
                openai_client=self._openai,
                qdrant_client=self._qdrant,
                collection_name=self.settings.QDRANT_COLLECTION_NAME,
                embedding_model=self.settings.OPENAI_EMBEDDING_MODEL,
            )
        except Exception:
            pass

    def _make_retriever(self, evaluation_id: str) -> Callable[[str], list[str]] | None:
        if self._qdrant is None or self._openai is None:
            return None
        openai_client = self._openai
        qdrant_client = self._qdrant
        collection_name = self.settings.QDRANT_COLLECTION_NAME
        embedding_model = self.settings.OPENAI_EMBEDDING_MODEL

        def retriever(query: str) -> list[str]:
            try:
                from services.api.app.project_evaluations.rag.retriever import retrieve_chunks
                return retrieve_chunks(
                    query=query,
                    evaluation_id=evaluation_id,
                    openai_client=openai_client,
                    qdrant_client=qdrant_client,
                    collection_name=collection_name,
                    embedding_model=embedding_model,
                )
            except Exception:
                return []

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
        artifact_rows = self.repository.list_artifact_rows(evaluation_id)
        area_rows = self.repository.list_area_rows(evaluation_id)
        retriever = self._make_retriever(evaluation_id)
        try:
            questions = generate_questions(
                evaluation_id,
                area_rows,
                context=context_row,
                artifacts=artifact_rows,
                llm=self._question_llm,
                retriever=retriever,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"AI 질문 생성 실패: {exc}",
            ) from exc
        saved = self.repository.save_questions(evaluation_id, questions)
        self.repository.update_evaluation_status(
            evaluation_id, EvaluationStatus.QUESTIONS_GENERATED
        )
        return saved

    def list_questions(self, evaluation_id: str) -> list[InterviewQuestionRead]:
        self.get_evaluation(evaluation_id)
        return self.repository.list_questions(evaluation_id)

    def verify_admin(
        self, evaluation_id: str, admin_password: str
    ) -> AdminVerifyRead:
        self.ensure_admin(evaluation_id, admin_password)
        return AdminVerifyRead(ok=True)

    def ensure_admin(self, evaluation_id: str, admin_password: str | None) -> None:
        row = self.repository.get_evaluation_row(evaluation_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="프로젝트 평가를 찾을 수 없습니다.",
            )
        if not admin_password or not row.admin_password_hash or not _verify_password(
            admin_password, row.admin_password_hash
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="관리자 비밀번호가 올바르지 않습니다.",
            )

    def join_evaluation(
        self, evaluation_id: str, participant_name: str, room_password: str
    ) -> JoinEvaluationRead:
        row = self.repository.get_evaluation_row(evaluation_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="프로젝트 평가를 찾을 수 없습니다.",
            )
        if not row.room_password_hash or not _verify_password(
            room_password, row.room_password_hash
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="방 비밀번호가 올바르지 않습니다.",
            )
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
            interview_url_path=f"/interview/{evaluation_id}/{session.id}",
        )

    def create_session(
        self,
        evaluation_id: str,
        participant_name: str = "",
        admin_password: str | None = None,
    ) -> InterviewSessionRead:
        self.ensure_admin(evaluation_id, admin_password)
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
        session = self.repository.create_session(evaluation_id, participant_name)
        self.repository.update_evaluation_status(
            evaluation_id, EvaluationStatus.INTERVIEWING
        )
        return session

    def submit_turn(
        self, evaluation_id: str, session_id: str, payload: InterviewTurnCreate
    ) -> InterviewTurnRead:
        session = self.ensure_session(evaluation_id, session_id)
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
        evaluation = evaluate_answer(question, payload.answer_text, llm=self._eval_llm)
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
        self, evaluation_id: str, session_id: str
    ) -> list[InterviewTurnRead]:
        self.ensure_session(evaluation_id, session_id)
        return self.repository.list_turns(session_id)

    def complete_session(
        self, evaluation_id: str, session_id: str
    ) -> EvaluationReportRead:
        session = self.ensure_session(evaluation_id, session_id)
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
        report = generate_report_payload(areas, questions, turns)
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
        self, evaluation_id: str, session_id: str
    ) -> InterviewSessionRead:
        session = self.repository.get_session(session_id)
        if session is None or session.evaluation_id != evaluation_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="인터뷰 세션을 찾을 수 없습니다.",
            )
        return session

    def submit_turns_bulk(
        self,
        evaluation_id: str,
        session_id: str,
        answer_texts: list[str],
    ) -> EvaluationReportRead:
        """Submit all voice interview answers at once and generate report.

        Maps answer_texts[i] → questions[i] by order_index.
        Used by the Realtime API proxy after interview ends.
        """
        questions = self.repository.list_question_rows(evaluation_id)
        n = min(len(questions), len(answer_texts))
        for i in range(n):
            text = answer_texts[i].strip() or "(답변 없음)"
            payload = InterviewTurnCreate(
                question_id=questions[i].id,
                answer_text=text,
            )
            self.submit_turn(evaluation_id, session_id, payload)
        return self.complete_session(evaluation_id, session_id)
