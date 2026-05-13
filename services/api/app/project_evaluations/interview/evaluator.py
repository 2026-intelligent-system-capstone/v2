from services.api.app.project_evaluations.analysis.llm_client import LlmClient
from services.api.app.project_evaluations.analysis.prompts import (
    FinalizeAnswerSchema,
    FollowUpQuestionSchema,
    JudgeAnswerSchema,
    build_finalize_prompt,
    build_follow_up_prompt,
    build_judge_prompt,
)
from services.api.app.project_evaluations.domain.models import (
    QuestionExchange,
    RubricCriterion,
    RubricScoreItem,
)
from services.api.app.project_evaluations.persistence.models import InterviewQuestionRow
from services.api.app.project_evaluations.persistence.repository import (
    refs_from_json,
    rubric_from_json,
)


def conversation_history_text(exchange: QuestionExchange | None) -> str:
    if exchange is None:
        return "(이전 대화 없음)"
    parts = [f"최초 답변: {exchange.student_answer.strip() or '(답변 없음)'}"]
    for index, follow_up in enumerate(exchange.follow_ups, start=1):
        parts.append(
            f"꼬리질문 {index}: {follow_up.question.strip()}\n"
            f"꼬리질문 필요 이유: {follow_up.reason.strip() or '(이유 없음)'}\n"
            f"학생 답변: {follow_up.answer.strip() or '(답변 없음)'}"
        )
    return "\n\n".join(parts)


def _source_snippets(question: InterviewQuestionRow) -> list[str]:
    source_refs = refs_from_json(question.source_refs_json)
    if not source_refs:
        raise RuntimeError("답변 평가에 사용할 question source refs가 없습니다.")
    return [f"{ref.path}: {ref.snippet}" for ref in source_refs if ref.snippet]


def judge_answer(
    question: InterviewQuestionRow,
    answer_text: str,
    llm: LlmClient | None = None,
    conversation_history: str = "",
    follow_up_count: int = 0,
) -> dict[str, object]:
    if llm is None or not llm.enabled():
        raise RuntimeError(
            "답변 평가에 필요한 LLM client가 비활성화되었습니다. OPENAI_API_KEY와 평가 모델 설정을 확인하세요."
        )
    result: JudgeAnswerSchema = llm.parse(
        build_judge_prompt(
            question=question.question,
            intent=question.intent,
            expected_signal=question.expected_signal,
            answer_text=answer_text,
            source_snippets=_source_snippets(question),
            conversation_history=conversation_history,
            follow_up_count=follow_up_count,
        ),
        JudgeAnswerSchema,
        max_tokens=1200,
    )
    reason = result.reason.strip()
    request_to_generator = result.request_to_generator.strip()
    if result.needs_follow_up and not request_to_generator:
        raise RuntimeError(
            "평가관이 꼬리질문 필요 판단을 했지만 생성기 요청이 비어 있습니다."
        )
    if not result.needs_follow_up and request_to_generator:
        raise RuntimeError(
            "평가관이 꼬리질문 불필요 판단을 했지만 생성기 요청을 함께 반환했습니다."
        )
    return {
        "needs_follow_up": result.needs_follow_up,
        "reason": reason,
        "request_to_generator": request_to_generator,
    }


def generate_follow_up_question(
    question: InterviewQuestionRow,
    answer_text: str,
    judge_reason: str,
    request_to_generator: str,
    llm: LlmClient | None = None,
    conversation_history: str = "",
) -> str:
    if llm is None or not llm.enabled():
        raise RuntimeError(
            "꼬리질문 생성에 필요한 LLM client가 비활성화되었습니다. OPENAI_API_KEY와 평가 모델 설정을 확인하세요."
        )
    result: FollowUpQuestionSchema = llm.parse(
        build_follow_up_prompt(
            question=question.question,
            intent=question.intent,
            expected_signal=question.expected_signal,
            answer_text=answer_text,
            judge_reason=judge_reason,
            request_to_generator=request_to_generator,
            source_snippets=_source_snippets(question),
            conversation_history=conversation_history,
        ),
        FollowUpQuestionSchema,
        max_tokens=800,
    )
    follow_up_question = result.follow_up_question.strip()
    if not follow_up_question:
        raise RuntimeError("꼬리질문 생성 결과가 비어 있습니다.")
    return follow_up_question


def finalize_oral_evaluation(
    question: InterviewQuestionRow,
    answer_text: str,
    llm: LlmClient | None = None,
    conversation_history: str = "",
) -> dict[str, object]:
    if llm is None or not llm.enabled():
        raise RuntimeError(
            "최종 루브릭 채점에 필요한 LLM client가 비활성화되었습니다. OPENAI_API_KEY와 평가 모델 설정을 확인하세요."
        )
    result: FinalizeAnswerSchema = llm.parse(
        build_finalize_prompt(
            question=question.question,
            intent=question.intent,
            expected_signal=question.expected_signal,
            answer_text=answer_text,
            source_snippets=_source_snippets(question),
            conversation_history=conversation_history,
        ),
        FinalizeAnswerSchema,
        max_tokens=2000,
    )

    expected_criteria = set(rubric_from_json(question.rubric_criteria_json))
    rubric_scores: list[RubricScoreItem] = []
    for item in result.rubric_scores:
        try:
            criterion = RubricCriterion(item.criterion)
        except ValueError as exc:
            raise RuntimeError(
                f"LLM이 지원하지 않는 루브릭 기준을 반환했습니다: {item.criterion}"
            ) from exc
        rubric_scores.append(
            RubricScoreItem(
                criterion=criterion,
                score=item.score,
                rationale=item.rationale,
            )
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
        "evidence_mismatches": [
            *result.evidence_mismatches,
            *result.missing_expected_signals,
        ],
        "suspicious_points": list(result.suspicious_points),
        "strengths": list(result.strengths),
    }


def evaluate_answer(
    question: InterviewQuestionRow,
    answer_text: str,
    llm: LlmClient | None = None,
    conversation_history: str = "",
    follow_up_count: int = 0,
) -> dict[str, object]:
    judge_result = judge_answer(
        question,
        answer_text,
        llm=llm,
        conversation_history=conversation_history,
        follow_up_count=follow_up_count,
    )
    if judge_result["needs_follow_up"]:
        follow_up_question = generate_follow_up_question(
            question,
            answer_text,
            judge_reason=str(judge_result["reason"]),
            request_to_generator=str(judge_result["request_to_generator"]),
            llm=llm,
            conversation_history=conversation_history,
        )
        return {
            "needs_follow_up": True,
            "follow_up_reason": str(judge_result["reason"]),
            "follow_up_question": follow_up_question,
        }
    finalized = finalize_oral_evaluation(
        question,
        answer_text,
        llm=llm,
        conversation_history=conversation_history,
    )
    return {
        "needs_follow_up": False,
        "follow_up_reason": "",
        "follow_up_question": None,
        **finalized,
    }
