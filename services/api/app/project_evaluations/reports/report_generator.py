from collections import defaultdict
from typing import Any

from services.api.app.project_evaluations.analysis.llm_client import LlmClient
from services.api.app.project_evaluations.analysis.prompts import ReportSchema, build_report_prompt
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
    llm: LlmClient | None = None,
    rubric_scores_by_turn: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    if llm is None or not llm.enabled():
        raise RuntimeError("최종 리포트 생성에 필요한 LLM client가 비활성화되었습니다. OPENAI_API_KEY와 평가 모델 설정을 확인하세요.")
    if not questions:
        raise RuntimeError("최종 리포트 생성에 필요한 인터뷰 질문이 없습니다.")
    if not turns:
        raise RuntimeError("최종 리포트 생성에 필요한 인터뷰 답변이 없습니다.")
    if len(turns) != len(questions):
        raise RuntimeError(
            f"리포트 생성 입력의 질문/답변 수가 일치하지 않습니다. questions={len(questions)}, turns={len(turns)}"
        )
    effective_scores = [
        turn.finalized_score if turn.finalized_score is not None else turn.score
        for turn in turns
    ]
    score = round(sum(effective_scores) / len(effective_scores), 2)
    questions_by_id = {question.id: question for question in questions}
    area_names = {area.id: area.name for area in areas}
    question_evaluations = []
    scores_by_area: dict[str, list[float]] = defaultdict(list)
    scores_by_bloom: dict[str, list[float]] = defaultdict(list)
    rubric_scores_by_criterion: dict[str, list[int]] = defaultdict(list)
    bloom_summary: dict[str, dict[str, Any]] = {}
    strengths = []
    suspicious_points = []
    evidence_alignment = []
    recommended_followups = []
    rubric_scores_by_turn = rubric_scores_by_turn or {}

    for turn in turns:
        question = questions_by_id.get(turn.question_id)
        if question is None:
            raise RuntimeError(f"답변에 연결된 질문을 찾을 수 없습니다. question_id={turn.question_id}")
        area_name = "프로젝트 전체"
        bloom_level = question.bloom_level
        if question.project_area_id:
            area_name = area_names.get(question.project_area_id, area_name)
        effective_score = turn.finalized_score if turn.finalized_score is not None else turn.score
        scores_by_area[area_name].append(effective_score)
        scores_by_bloom[bloom_level].append(effective_score)
        strengths.extend(from_json(turn.strengths_json, []))
        suspicious_points.extend(from_json(turn.suspicious_points_json, []))
        evidence_alignment.extend(from_json(turn.evidence_matches_json, []))
        source_refs = from_json(question.source_refs_json, [])
        if not source_refs:
            raise RuntimeError(f"리포트 입력 질문에 source refs가 없습니다. question_id={question.id}")
        rubric_scores = rubric_scores_by_turn.get(turn.id, [])
        if not rubric_scores:
            raise RuntimeError(f"리포트 입력 답변에 루브릭 점수 상세가 없습니다. turn_id={turn.id}")
        for rubric_score in rubric_scores:
            rubric_scores_by_criterion[str(rubric_score["criterion"])].append(int(rubric_score["score"]))
        if turn.follow_up_question and turn.finalized_score is None:
            recommended_followups.append(turn.follow_up_question)
        question_evaluations.append(
            {
                "question_id": turn.question_id,
                "question": turn.question_text,
                "answer_preview": turn.answer_text[:500],
                "score": effective_score,
                "summary": turn.evaluation_summary,
                "area": area_name,
                "bloom_level": bloom_level,
                "source_refs": source_refs,
                "rubric_scores": rubric_scores,
                "evidence_matches": from_json(turn.evidence_matches_json, []),
                "evidence_mismatches": from_json(turn.evidence_mismatches_json, []),
                "suspicious_points": from_json(turn.suspicious_points_json, []),
                "follow_up_question": turn.follow_up_question,
                "needs_follow_up": bool(turn.follow_up_question and turn.finalized_score is None),
            }
        )

    for bloom_level, values in sorted(scores_by_bloom.items()):
        bloom_summary[bloom_level] = {
            "question_count": len(values),
            "average_score": round(sum(values) / len(values), 2),
        }

    area_source_refs = {
        area.name: from_json(area.source_refs_json, [])
        for area in areas
    }
    area_analyses = [
        {
            "area": area,
            "score_average": round(sum(values) / max(1, len(values)), 2),
            "question_count": len(values),
            "source_refs": area_source_refs.get(area, []),
        }
        for area, values in sorted(scores_by_area.items())
    ]
    rubric_summary = {
        criterion: {
            "average_score": round(sum(values) / len(values), 2),
            "max_score": 3,
            "question_count": len(values),
        }
        for criterion, values in sorted(rubric_scores_by_criterion.items())
    }
    rubric_summary["overall"] = {
        "evaluation_method": "질문별 구술형 rubric score를 criterion별로 집계하고 최종 리포트 LLM이 재해석",
        "average_score": score,
        "turn_count": len(turns),
        "follow_up_required_count": sum(
            1 for turn in turns if turn.follow_up_question and turn.finalized_score is None
        ),
    }
    report_input = {
        "preliminary_score_average": score,
        "area_analyses": area_analyses,
        "question_evaluations": question_evaluations,
        "bloom_summary": dict(bloom_summary),
        "rubric_summary": rubric_summary,
        "evidence_alignment": unique(evidence_alignment),
        "strengths": unique(strengths),
        "suspicious_points": unique(suspicious_points),
        "recommended_followups": unique(recommended_followups),
    }
    result: ReportSchema = llm.parse(
        build_report_prompt(report_input),
        ReportSchema,
        max_tokens=4000,
    )
    try:
        decision = FinalDecision(result.final_decision)
    except ValueError as exc:
        raise RuntimeError(f"LLM이 지원하지 않는 최종 판정을 반환했습니다: {result.final_decision}") from exc
    return {
        "final_decision": decision,
        "authenticity_score": result.authenticity_score,
        "summary": result.summary,
        "area_analyses": [item.model_dump() for item in result.area_analyses],
        "question_evaluations": [item.model_dump() for item in result.question_evaluations],
        "bloom_summary": {
            item.bloom_level: {"question_count": item.question_count, "average_score": item.average_score}
            for item in result.bloom_summary
        },
        "rubric_summary": {
            item.criterion: {"average_score": item.average_score, "question_count": item.question_count}
            for item in result.rubric_summary
        },
        "evidence_alignment": result.evidence_alignment,
        "strengths": result.strengths,
        "suspicious_points": result.suspicious_points,
        "recommended_followups": result.recommended_followups,
    }


def unique(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result[:12]
