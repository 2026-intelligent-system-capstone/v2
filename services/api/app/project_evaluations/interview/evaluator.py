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

SPECIFIC_MARKERS = (
    "파일",
    "함수",
    "클래스",
    "모듈",
    "API",
    "DB",
    "데이터",
    "에러",
    "테스트",
    "설정",
)
AVOIDANCE_MARKERS = ("잘 모르", "기억 안", "모릅니다", "몰라", "대충", "아마")


def evaluate_answer(
    question: InterviewQuestionRow,
    answer_text: str,
    llm: LlmClient | None = None,
) -> dict[str, object]:
    if llm and llm.enabled():
        try:
            return _evaluate_with_llm(question, answer_text, llm)
        except Exception:
            pass
    return _evaluate_rule_based(question, answer_text)


def _evaluate_with_llm(
    question: InterviewQuestionRow,
    answer_text: str,
    llm: LlmClient,
) -> dict[str, object]:
    source_refs = refs_from_json(question.source_refs_json)
    snippets = [f"{r.path}: {r.snippet}" for r in source_refs if r.snippet]
    messages = build_eval_prompt(
        question=question.question,
        intent=question.intent,
        expected_signal=question.expected_signal,
        answer_text=answer_text,
        source_snippets=snippets,
    )
    result: AnswerEvalSchema = llm.parse(messages, AnswerEvalSchema, max_tokens=2000)

    rubric_scores = []
    for item in result.rubric_scores:
        try:
            criterion = RubricCriterion(item.criterion)
        except ValueError:
            continue
        rubric_scores.append(
            RubricScoreItem(criterion=criterion, score=item.score, rationale=item.rationale)
        )

    if not rubric_scores:
        rubric_scores = _fallback_rubric_scores(question)

    return {
        "score": result.score,
        "evaluation_summary": result.evaluation_summary,
        "rubric_scores": rubric_scores,
        "evidence_matches": result.evidence_matches,
        "evidence_mismatches": result.evidence_mismatches,
        "suspicious_points": result.suspicious_points,
        "strengths": result.strengths,
        "follow_up_question": result.follow_up_question,
    }


def _evaluate_rule_based(
    question: InterviewQuestionRow, answer_text: str
) -> dict[str, object]:
    rubric = rubric_from_json(question.rubric_criteria_json)
    source_refs = refs_from_json(question.source_refs_json)
    answer_lower = answer_text.lower()
    source_keywords = _collect_source_keywords(source_refs)
    matched_keywords = [kw for kw in source_keywords if kw.lower() in answer_lower]
    specificity_hits = [m for m in SPECIFIC_MARKERS if m.lower() in answer_lower]
    is_avoidant = any(m in answer_lower for m in AVOIDANCE_MARKERS)

    base_score = 1
    if len(answer_text) >= 120:
        base_score += 1
    if matched_keywords or specificity_hits:
        base_score += 1
    if is_avoidant:
        base_score = max(0, base_score - 1)
    base_score = min(3, base_score)

    rubric_scores = []
    for criterion in rubric:
        score = _criterion_score(
            criterion, base_score, matched_keywords, specificity_hits, is_avoidant
        )
        rubric_scores.append(
            RubricScoreItem(
                criterion=criterion,
                score=score,
                rationale=_build_rationale(
                    criterion, score, matched_keywords, specificity_hits, is_avoidant
                ),
            )
        )

    average = sum(item.score for item in rubric_scores) / max(1, len(rubric_scores))
    strengths, suspicious_points, evidence_matches, evidence_mismatches = [], [], [], []

    if matched_keywords:
        evidence_matches.append(
            "자료 경로/키워드를 답변에 일부 연결했습니다: " + ", ".join(matched_keywords[:5])
        )
        strengths.append("자료 기반 세부사항을 일부 언급했습니다.")
    else:
        evidence_mismatches.append(
            "답변에서 질문의 source reference와 직접 연결되는 키워드가 부족합니다."
        )
    if specificity_hits:
        strengths.append(
            "구현 단위 표현이 포함되어 있습니다: " + ", ".join(specificity_hits[:5])
        )
    if is_avoidant or average < 1.5:
        suspicious_points.append("답변이 회피적이거나 구현 구체성이 낮습니다.")

    follow_up_question = None
    if average < 2:
        follow_up_question = (
            "방금 답변한 내용을 실제 파일명이나 함수명 하나와 연결해서 더 구체적으로 설명해주세요."
        )

    return {
        "score": round(average / 3 * 100, 2),
        "evaluation_summary": _summarize_score(average),
        "rubric_scores": rubric_scores,
        "evidence_matches": evidence_matches,
        "evidence_mismatches": evidence_mismatches,
        "suspicious_points": suspicious_points,
        "strengths": strengths,
        "follow_up_question": follow_up_question,
    }


def _fallback_rubric_scores(question: InterviewQuestionRow) -> list[RubricScoreItem]:
    rubric = rubric_from_json(question.rubric_criteria_json)
    return [
        RubricScoreItem(criterion=c, score=1, rationale="LLM 평가 결과 파싱 실패로 기본 점수 적용")
        for c in rubric
    ]


def _collect_source_keywords(source_refs: list[object]) -> list[str]:
    keywords = []
    for ref in source_refs:
        path_parts = [p for p in ref.path.replace("-", "_").split("/") if p]
        keywords.extend(p.lower() for p in path_parts if len(p) >= 4)
    return sorted(set(keywords))[:12]


def _criterion_score(
    criterion: RubricCriterion,
    base_score: int,
    matched_keywords: list[str],
    specificity_hits: list[str],
    is_avoidant: bool,
) -> int:
    score = base_score
    if criterion == RubricCriterion.EVIDENCE_ALIGNMENT and not matched_keywords:
        score = min(score, 1)
    if criterion == RubricCriterion.IMPLEMENTATION_SPECIFICITY and not specificity_hits:
        score = min(score, 1)
    if criterion == RubricCriterion.ANSWER_CONSISTENCY and is_avoidant:
        score = min(score, 1)
    return max(0, min(3, score))


def _build_rationale(
    criterion: RubricCriterion,
    score: int,
    matched_keywords: list[str],
    specificity_hits: list[str],
    is_avoidant: bool,
) -> str:
    if is_avoidant:
        return f"{criterion.value}: 회피성 표현이 있어 {score}점으로 평가했습니다."
    if matched_keywords or specificity_hits:
        return f"{criterion.value}: 자료 키워드 또는 구현 단위 표현이 있어 {score}점으로 평가했습니다."
    return f"{criterion.value}: 구체 근거가 부족해 {score}점으로 평가했습니다."


def _summarize_score(average: float) -> str:
    if average >= 2.5:
        return "자료와 구현 경험이 비교적 구체적으로 연결된 답변입니다."
    if average >= 1.5:
        return "일부 이해는 보이나 실제 구현 근거를 더 확인해야 합니다."
    return "프로젝트 수행 경험을 확인하기에는 구체성이 부족합니다."
