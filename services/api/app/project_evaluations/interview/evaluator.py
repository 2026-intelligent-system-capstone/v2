from services.api.app.project_evaluations.analysis.llm_client import LlmClient
from services.api.app.project_evaluations.analysis.prompts import (
    AnswerEvalSchema,
    build_eval_prompt,
)
from services.api.app.project_evaluations.domain.models import (
    RubricCriterion,
    RubricScoreItem,
)
from services.api.app.project_evaluations.persistence.models import InterviewQuestionRow
from services.api.app.project_evaluations.persistence.repository import (
    refs_from_json,
    rubric_from_json,
)

def evaluate_answer(
    question: InterviewQuestionRow,
    answer_text: str,
    llm: LlmClient | None = None,
) -> dict[str, object]:
    if llm is None or not llm.enabled():
        raise RuntimeError("답변 평가에 필요한 LLM client가 비활성화되었습니다. OPENAI_API_KEY와 평가 모델 설정을 확인하세요.")
    return _evaluate_with_llm(question, answer_text, llm)


def _evaluate_with_llm(
    question: InterviewQuestionRow,
    answer_text: str,
    llm: LlmClient,
) -> dict[str, object]:
    source_refs = refs_from_json(question.source_refs_json)
    if not source_refs:
        raise RuntimeError("답변 평가에 사용할 question source refs가 없습니다.")
    snippets = [f"{r.path}: {r.snippet}" for r in source_refs if r.snippet]
    messages = build_eval_prompt(
        question=question.question,
        intent=question.intent,
        expected_signal=question.expected_signal,
        answer_text=answer_text,
        source_snippets=snippets,
    )
    result: AnswerEvalSchema = llm.parse(messages, AnswerEvalSchema, max_tokens=2000)

    expected_criteria = set(rubric_from_json(question.rubric_criteria_json))
    rubric_scores = []
    for item in result.rubric_scores:
        try:
            criterion = RubricCriterion(item.criterion)
        except ValueError as exc:
            raise RuntimeError(f"LLM이 지원하지 않는 루브릭 기준을 반환했습니다: {item.criterion}") from exc
        rubric_scores.append(
            RubricScoreItem(criterion=criterion, score=item.score, rationale=item.rationale)
        )

    returned_criteria = {item.criterion for item in rubric_scores}
    if returned_criteria != expected_criteria:
        raise RuntimeError(
            "LLM 평가 결과의 루브릭 기준이 질문 기준과 일치하지 않습니다. "
            f"expected={sorted(c.value for c in expected_criteria)}, "
            f"actual={sorted(c.value for c in returned_criteria)}"
        )

    return {
        "score": result.score,
        "evaluation_summary": result.evaluation_summary,
        "rubric_scores": rubric_scores,
        "evidence_matches": [*result.evidence_matches, *result.authenticity_signals],
        "evidence_mismatches": [*result.evidence_mismatches, *result.missing_expected_signals],
        "suspicious_points": result.suspicious_points,
        "strengths": result.strengths,
        "follow_up_question": result.follow_up_question,
    }
