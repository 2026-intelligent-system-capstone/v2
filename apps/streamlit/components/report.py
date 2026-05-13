"""Report rendering components for the Streamlit app.

리포트 화면은 다음 네 탭으로 구성된다.
1. 개요: 최종 판정, 신뢰도, Bloom/Rubric 분포 차트, 강점·의심점·추가 질문 요약.
2. 질문별 상세: 각 질문 카드에 문항·의도·내 답변·꼬리질문 흐름·점수 근거.
3. 영역 분석: 프로젝트 영역별 평균 점수와 분포.
4. 원본 데이터: 디버깅용 raw JSON.

`_merge_report_payload`는 report·questions·turns 세 응답을 question_id 기준으로 합쳐
질문별 카드가 한 번에 모든 정보를 표시할 수 있도록 한다.
"""

from __future__ import annotations

from typing import Any

import streamlit as st


_FINAL_DECISION_CHIP_STYLE: dict[str, tuple[str, str]] = {
    "검증 통과": ("#0E8A4A", "#E6F4EC"),
    "추가 확인 필요": ("#A86A00", "#FBEFD8"),
    "신뢰 낮음": ("#B3261E", "#FBE5E3"),
}

_BLOOM_ORDER = ["기억", "이해", "적용", "분석", "평가", "창안"]

_RUBRIC_LABELS: dict[str, str] = {
    "source_alignment": "근거 일치도",
    "implementation_specificity": "구현 구체성",
    "structural_understanding": "구조 이해도",
    "decision_reasoning": "의사결정 이해도",
    "troubleshooting_experience": "트러블슈팅 경험",
    "limitation_awareness": "한계 인식",
    "answer_consistency": "답변 일관성",
}

_MISSING_HINT = "데이터 없음"


def render_report(
    report: dict[str, Any],
    questions: list[dict[str, Any]] | None = None,
    turns: list[dict[str, Any]] | None = None,
    *,
    questions_error: str = "",
    turns_error: str = "",
) -> None:
    """리포트 진입점. 4탭 구조로 렌더링한다.

    `questions`/`turns`가 None이면 해당 응답을 받지 못한 상태로 간주하고
    상단에 에러 배너를 표시한 뒤, report 자체 필드만으로 가능한 만큼 렌더한다.
    누락된 정보는 카드 내부에서 회색 캡션으로 명시한다.
    """
    st.header("최종 리포트")

    _render_decision_chip(report)

    if questions_error:
        st.warning(f"질문 메타 정보 불러오기 실패: {questions_error}")
    if turns_error:
        st.warning(
            f"답변/꼬리질문 상세 불러오기 실패: {turns_error}. "
            "세션 토큰이 없거나 만료된 경우일 수 있습니다."
        )

    merged = _merge_report_payload(report, questions or [], turns or [])

    tab_overview, tab_questions, tab_areas, tab_raw = st.tabs(
        ["개요", "질문별 상세", "영역 분석", "원본 데이터"]
    )
    with tab_overview:
        _render_report_overview(merged)
    with tab_questions:
        _render_question_cards(merged)
    with tab_areas:
        _render_area_breakdown(merged)
    with tab_raw:
        _render_raw_data(report, questions, turns)


def _merge_report_payload(
    report: dict[str, Any],
    questions: list[dict[str, Any]],
    turns: list[dict[str, Any]],
) -> dict[str, Any]:
    """report 안의 question_evaluations에 questions/turns 데이터를 question_id로 머지.

    순수 함수. report 원본은 수정하지 않고 얕은 복사 dict를 새로 만든다.
    누락된 필드는 빈 값으로 채우되, 화면에서 회색 캡션으로 표시할 수 있도록
    `_missing_*` 플래그를 함께 남긴다.
    """
    questions_by_id = {str(q.get("id", "")): q for q in questions if q.get("id")}
    turns_by_question = {
        str(t.get("question_id", "")): t for t in turns if t.get("question_id")
    }

    enriched_evaluations: list[dict[str, Any]] = []
    for item in report.get("question_evaluations", []) or []:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("question_id", ""))
        question_meta = questions_by_id.get(qid, {})
        turn_meta = turns_by_question.get(qid, {})
        conversation = turn_meta.get("conversation_history") or {}
        if not isinstance(conversation, dict):
            conversation = {}

        merged_item = dict(item)
        merged_item["intent"] = question_meta.get("intent", "")
        merged_item["verification_focus"] = question_meta.get("verification_focus", "")
        merged_item["expected_signal"] = question_meta.get("expected_signal", "")
        merged_item["expected_evidence"] = question_meta.get("expected_evidence", "")
        merged_item["difficulty"] = question_meta.get("difficulty", "")
        merged_item["order_index"] = question_meta.get("order_index", -1)

        merged_item["answer_text_full"] = turn_meta.get("answer_text", "")
        merged_item["follow_up_reason"] = turn_meta.get("follow_up_reason", "")
        merged_item["conversation_history"] = conversation
        merged_item["turn_finalized_score"] = turn_meta.get("finalized_score")

        merged_item["_missing_question_meta"] = not bool(question_meta)
        merged_item["_missing_turn_meta"] = not bool(turn_meta)
        enriched_evaluations.append(merged_item)

    enriched_evaluations.sort(
        key=lambda x: (
            x.get("order_index") if x.get("order_index", -1) >= 0 else 999999,
            str(x.get("question_id", "")),
        )
    )

    return {**report, "question_evaluations": enriched_evaluations}


def _render_decision_chip(report: dict[str, Any]) -> None:
    decision = str(report.get("final_decision", "-"))
    fg, bg = _FINAL_DECISION_CHIP_STYLE.get(decision, ("#444", "#EEE"))
    st.markdown(
        f"""
        <div style="display:inline-block;padding:6px 14px;border-radius:999px;
                    background:{bg};color:{fg};font-weight:600;font-size:14px;
                    border:1px solid {fg}33;">
            최종 판정 · {decision}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_report_overview(merged: dict[str, Any]) -> None:
    evaluations = merged.get("question_evaluations", []) or []
    score_values = [
        float(item.get("score", 0) or 0)
        for item in evaluations
        if isinstance(item.get("score"), (int, float))
    ]
    avg_score = sum(score_values) / len(score_values) if score_values else 0.0
    pending_followups = sum(
        1
        for item in evaluations
        if item.get("needs_follow_up") and item.get("follow_up_question")
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("신뢰도 점수", f"{float(merged.get('authenticity_score', 0) or 0):.1f}")
    col2.metric("총 질문 수", len(evaluations))
    col3.metric("평균 점수", f"{avg_score:.1f}")
    col4.metric("미완료 꼬리질문", pending_followups)

    st.subheader("요약")
    summary_text = str(merged.get("summary", "")).strip()
    if summary_text:
        st.write(summary_text)
    else:
        st.caption(_MISSING_HINT)

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.subheader("Bloom 단계별 평균")
        _render_bloom_chart(merged.get("bloom_summary", []))
    with chart_col2:
        st.subheader("Rubric 기준별 평균")
        _render_rubric_chart(merged.get("rubric_summary", []))

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.subheader("강점")
        _render_bullet_list(merged.get("strengths", []))
    with col_b:
        st.subheader("의심 지점")
        _render_bullet_list(merged.get("suspicious_points", []))
    with col_c:
        st.subheader("추가 확인 질문")
        _render_bullet_list(merged.get("recommended_followups", []))

    evidence = merged.get("evidence_alignment", []) or []
    if evidence:
        st.subheader("근거 일치")
        _render_bullet_list(evidence)


def _render_bloom_chart(bloom_summary: Any) -> None:
    if not isinstance(bloom_summary, list) or not bloom_summary:
        st.caption(_MISSING_HINT)
        return
    data: dict[str, float] = {}
    for entry in bloom_summary:
        if not isinstance(entry, dict):
            continue
        level = str(entry.get("bloom_level", ""))
        score = float(entry.get("average_score", 0) or 0)
        if level:
            data[level] = score
    if not data:
        st.caption(_MISSING_HINT)
        return
    ordered = {level: data[level] for level in _BLOOM_ORDER if level in data}
    leftover = {k: v for k, v in data.items() if k not in ordered}
    ordered.update(leftover)
    st.bar_chart(ordered, y_label="평균 점수")


def _render_rubric_chart(rubric_summary: Any) -> None:
    if not isinstance(rubric_summary, list) or not rubric_summary:
        st.caption(_MISSING_HINT)
        return
    data: dict[str, float] = {}
    for entry in rubric_summary:
        if not isinstance(entry, dict):
            continue
        criterion = str(entry.get("criterion", ""))
        if not criterion or criterion == "overall":
            continue
        label = _RUBRIC_LABELS.get(criterion, criterion)
        score = float(entry.get("average_score", 0) or 0)
        data[label] = score
    if not data:
        st.caption(_MISSING_HINT)
        return
    st.bar_chart(data, y_label="평균(0~3)")


def _render_bullet_list(items: Any) -> None:
    if not isinstance(items, list) or not items:
        st.caption(_MISSING_HINT)
        return
    rendered = 0
    for entry in items:
        text = str(entry).strip()
        if text:
            st.markdown(f"- {text}")
            rendered += 1
    if rendered == 0:
        st.caption(_MISSING_HINT)


def _render_question_cards(merged: dict[str, Any]) -> None:
    evaluations = merged.get("question_evaluations", []) or []
    if not evaluations:
        st.info("질문별 평가 데이터가 없습니다.")
        return

    sort_label = st.selectbox(
        "정렬",
        ["문항 순서", "점수 낮은 순", "점수 높은 순"],
        index=0,
        key="report_question_sort",
    )
    if sort_label == "점수 낮은 순":
        evaluations = sorted(
            evaluations, key=lambda x: float(x.get("score", 0) or 0)
        )
    elif sort_label == "점수 높은 순":
        evaluations = sorted(
            evaluations,
            key=lambda x: float(x.get("score", 0) or 0),
            reverse=True,
        )

    for idx, item in enumerate(evaluations, start=1):
        _render_question_card(idx, item)


def _render_question_card(idx: int, item: dict[str, Any]) -> None:
    bloom = str(item.get("bloom_level", "-"))
    area = str(item.get("area", "-"))
    score_value = item.get("score", 0)
    try:
        score_text = f"{float(score_value):.0f}"
    except (TypeError, ValueError):
        score_text = "-"
    label = f"Q{idx} · [{bloom}] · 점수 {score_text} · 영역: {area}"

    with st.expander(label, expanded=False):
        question_text = str(item.get("question", "")).strip()
        if question_text:
            st.markdown(f"### {question_text}")
        else:
            st.caption(_MISSING_HINT)

        meta_parts: list[str] = []
        intent = str(item.get("intent", "")).strip()
        if intent:
            meta_parts.append(f"**검증 의도**: {intent}")
        verification_focus = str(item.get("verification_focus", "")).strip()
        if verification_focus:
            meta_parts.append(f"**검증 포커스**: {verification_focus}")
        expected_signal = str(item.get("expected_signal", "")).strip()
        if expected_signal:
            meta_parts.append(f"**기대 신호**: {expected_signal}")
        if meta_parts:
            st.caption("  ·  ".join(meta_parts))
        elif item.get("_missing_question_meta"):
            st.caption(f"질문 메타: {_MISSING_HINT}")

        st.markdown("#### 내 답변")
        answer_full = str(item.get("answer_text_full", "")).strip()
        answer_preview = str(item.get("answer_preview", "")).strip()
        if answer_full:
            st.markdown(_blockquote(answer_full))
        elif answer_preview:
            st.markdown(_blockquote(answer_preview))
            st.caption("답변 전문 미수신 — 처음 500자만 표시")
        else:
            st.caption(_MISSING_HINT)

        _render_follow_up_section(item)
        _render_score_rationale(item)
        _render_source_refs(item.get("source_refs", []))


def _render_follow_up_section(item: dict[str, Any]) -> None:
    follow_up_question = str(item.get("follow_up_question", "") or "").strip()
    conversation = item.get("conversation_history") or {}
    follow_ups = (
        conversation.get("follow_ups", []) if isinstance(conversation, dict) else []
    )
    if not follow_up_question and not follow_ups:
        return

    st.markdown("#### 꼬리질문 흐름")
    reason = str(item.get("follow_up_reason", "") or "").strip()
    if reason:
        st.markdown(f"> **생성 이유**: {reason}")
    elif item.get("_missing_turn_meta"):
        st.caption(f"생성 이유: {_MISSING_HINT} (세션 토큰 부재로 상세 미수신)")

    if isinstance(follow_ups, list) and follow_ups:
        for i, exchange in enumerate(follow_ups, start=1):
            if not isinstance(exchange, dict):
                continue
            q_text = str(exchange.get("question", "")).strip()
            a_text = str(exchange.get("answer", "")).strip()
            ex_reason = str(exchange.get("reason", "")).strip()
            if ex_reason and ex_reason != reason:
                st.caption(f"#{i} 트리거: {ex_reason}")
            if q_text:
                st.markdown(f"**Q{i}.** {q_text}")
            if a_text:
                st.markdown(_blockquote(a_text))
            else:
                st.caption("학생 응답 없음")
    elif follow_up_question:
        st.markdown(f"**Q.** {follow_up_question}")
        st.caption("학생의 꼬리질문 답변이 기록되지 않았습니다.")


def _render_score_rationale(item: dict[str, Any]) -> None:
    st.markdown("#### 점수 근거")
    summary = str(item.get("summary", "")).strip()
    if summary:
        st.write(summary)
    else:
        st.caption(_MISSING_HINT)

    rubric_scores = item.get("rubric_scores", []) or []
    if isinstance(rubric_scores, list) and rubric_scores:
        table_rows: list[dict[str, Any]] = []
        for entry in rubric_scores:
            if not isinstance(entry, dict):
                continue
            criterion_raw = str(entry.get("criterion", ""))
            table_rows.append(
                {
                    "기준": _RUBRIC_LABELS.get(criterion_raw, criterion_raw),
                    "점수(0~3)": entry.get("score"),
                    "사유": str(entry.get("rationale", "")).strip(),
                }
            )
        if table_rows:
            st.dataframe(table_rows, width="stretch", hide_index=True)
    else:
        st.caption(f"루브릭 점수: {_MISSING_HINT}")

    col_match, col_mismatch, col_susp, col_strength = st.columns(4)
    with col_match:
        st.markdown("**근거 일치**")
        _render_bullet_list(item.get("evidence_matches", []))
    with col_mismatch:
        st.markdown("**근거 불일치**")
        _render_bullet_list(item.get("evidence_mismatches", []))
    with col_susp:
        st.markdown("**의심 지점**")
        _render_bullet_list(item.get("suspicious_points", []))
    with col_strength:
        st.markdown("**강점**")
        _render_bullet_list(item.get("strengths", []))


def _render_source_refs(source_refs: Any) -> None:
    if not isinstance(source_refs, list) or not source_refs:
        return
    st.markdown("#### 참조 자료")
    for ref in source_refs:
        if not isinstance(ref, dict):
            continue
        path = str(ref.get("path", "")).strip()
        role = str(ref.get("artifact_role", "")).strip()
        chunk_type = str(ref.get("chunk_type", "")).strip()
        meta_parts = [part for part in (role, chunk_type) if part]
        meta_suffix = f" · {' · '.join(meta_parts)}" if meta_parts else ""
        snippet = str(ref.get("snippet", "")).strip()
        if path:
            st.markdown(f"- `{path}`{meta_suffix}")
        elif meta_parts:
            st.markdown(f"- {' · '.join(meta_parts)}")
        if snippet:
            with st.expander("스니펫 보기", expanded=False):
                st.code(snippet)


def _render_area_breakdown(merged: dict[str, Any]) -> None:
    areas = merged.get("area_analyses", []) or []
    if not isinstance(areas, list) or not areas:
        st.info("영역별 분석 데이터가 없습니다.")
        return

    table_rows: list[dict[str, Any]] = []
    chart_data: dict[str, float] = {}
    for entry in areas:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("area", "-"))
        avg = float(entry.get("score_average", 0) or 0)
        count = int(entry.get("question_count", 0) or 0)
        source_refs = entry.get("source_refs", []) or []
        ref_preview = ", ".join(
            str(r.get("path", ""))
            for r in source_refs
            if isinstance(r, dict) and r.get("path")
        )[:200]
        table_rows.append(
            {
                "영역": name,
                "평균 점수": round(avg, 1),
                "질문 수": count,
                "대표 근거": ref_preview or "-",
            }
        )
        if name:
            chart_data[name] = avg

    if table_rows:
        st.dataframe(table_rows, width="stretch", hide_index=True)
    if chart_data:
        st.subheader("영역별 평균 점수")
        st.bar_chart(chart_data, y_label="평균 점수")


def _render_raw_data(
    report: dict[str, Any],
    questions: list[dict[str, Any]] | None,
    turns: list[dict[str, Any]] | None,
) -> None:
    st.caption("디버깅·검증용 raw payload입니다.")
    with st.expander("리포트 JSON", expanded=False):
        st.json(report)
    if questions is not None:
        with st.expander(f"질문 메타 ({len(questions)}건)", expanded=False):
            st.json(questions)
    if turns is not None:
        with st.expander(f"턴 상세 ({len(turns)}건)", expanded=False):
            st.json(turns)


def _blockquote(text: str) -> str:
    """st.markdown용 인용 블록. 여러 줄 입력도 안전하게 처리."""
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(f"> {line}" for line in lines)
