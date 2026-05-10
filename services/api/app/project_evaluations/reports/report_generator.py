from collections import defaultdict
from typing import Any

from services.api.app.project_evaluations.domain.models import FinalDecision
from services.api.app.project_evaluations.persistence.models import (
    InterviewQuestionRow,
    InterviewTurnRow,
    ProjectAreaRow,
)
from services.api.app.project_evaluations.persistence.repository import from_json


def generate_report_payload(
    areas: list[ProjectAreaRow],
    questions: list[InterviewQuestionRow],
    turns: list[InterviewTurnRow],
) -> dict[str, Any]:
    score = round(sum(turn.score for turn in turns) / max(1, len(turns)), 2)
    decision = decide(score)
    questions_by_id = {question.id: question for question in questions}
    area_names = {area.id: area.name for area in areas}
    question_evaluations = []
    scores_by_area: dict[str, list[float]] = defaultdict(list)
    bloom_summary: dict[str, int] = defaultdict(int)
    strengths = []
    suspicious_points = []
    evidence_alignment = []
    recommended_followups = []

    for turn in turns:
        question = questions_by_id.get(turn.question_id)
        area_name = "프로젝트 전체"
        bloom_level = "미분류"
        if question is not None:
            bloom_level = question.bloom_level
            bloom_summary[bloom_level] += 1
            if question.project_area_id:
                area_name = area_names.get(question.project_area_id, area_name)
        scores_by_area[area_name].append(turn.score)
        strengths.extend(from_json(turn.strengths_json, []))
        suspicious_points.extend(from_json(turn.suspicious_points_json, []))
        evidence_alignment.extend(from_json(turn.evidence_matches_json, []))
        recommended_followups.extend(from_json(turn.evidence_mismatches_json, []))
        if turn.follow_up_question:
            recommended_followups.append(turn.follow_up_question)
        question_evaluations.append(
            {
                "question_id": turn.question_id,
                "question": turn.question_text,
                "answer_preview": turn.answer_text[:300],
                "score": turn.score,
                "summary": turn.evaluation_summary,
                "area": area_name,
                "bloom_level": bloom_level,
            }
        )

    area_analyses = [
        {
            "area": area,
            "confidence": round(sum(values) / max(1, len(values)), 2),
            "question_count": len(values),
        }
        for area, values in sorted(scores_by_area.items())
    ]
    rubric_summary = {
        "평가 방식": "0~3점 루브릭을 질문별 100점 환산 점수로 집계",
        "평균 점수": score,
    }
    return {
        "final_decision": decision,
        "authenticity_score": score,
        "summary": f"총 {len(turns)}개 답변 기준 최종 판정은 '{decision.value}'입니다.",
        "area_analyses": area_analyses,
        "question_evaluations": question_evaluations,
        "bloom_summary": dict(bloom_summary),
        "rubric_summary": rubric_summary,
        "evidence_alignment": unique(evidence_alignment),
        "strengths": unique(strengths),
        "suspicious_points": unique(suspicious_points),
        "recommended_followups": unique(recommended_followups),
    }


def decide(score: float) -> FinalDecision:
    if score >= 75:
        return FinalDecision.VERIFIED
    if score >= 50:
        return FinalDecision.NEEDS_FOLLOWUP
    return FinalDecision.LOW_CONFIDENCE


def unique(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result[:12]
