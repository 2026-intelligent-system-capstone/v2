from services.api.app.project_evaluations.persistence.repository import (
    ProjectEvaluationRepository,
)


def ensure_session_belongs_to_evaluation(
    repository: ProjectEvaluationRepository, evaluation_id: str, session_id: str
) -> bool:
    session = repository.get_session(session_id)
    return session is not None and session.evaluation_id == evaluation_id
