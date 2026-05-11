import os
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlencode

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.streamlit.api_client import (
    ApiClientError,
    create_evaluation,
    extract_evaluation,
    generate_questions,
    get_api_base_url,
    get_health,
    get_latest_report,
    join_evaluation,
    upload_zip,
    verify_admin,
)

st.set_page_config(page_title="프로젝트 수행 진위 평가", layout="wide")

BLOOM_LEVELS = ["기억", "이해", "적용", "분석", "평가", "창안"]

REASON_LABELS = {
    "accepted": "추출 성공",
    "ignored": "무시됨",
    "empty_text": "텍스트 없음",
    "file_too_large": "용량 초과",
    "processed_file_limit": "처리 제한",
    "extract_failed": "실패",
    "unsupported_extension": "지원하지 않는 확장자",
    "ignored_path": "무시 경로",
}


DIFFICULTY_LABELS = {
    "easy": "쉬움",
    "medium": "보통",
    "hard": "어려움",
}


def calculate_bloom_distribution(
    total_questions: int, ratios: dict[str, int]
) -> dict[str, int]:
    ratio_sum = sum(ratios.values())
    if ratio_sum == 0:
        return {level: 0 for level in BLOOM_LEVELS}

    raw_counts = {
        level: total_questions * ratios[level] / ratio_sum for level in BLOOM_LEVELS
    }
    planned_counts = {level: int(raw_counts[level]) for level in BLOOM_LEVELS}
    remaining = total_questions - sum(planned_counts.values())
    remainders = sorted(
        BLOOM_LEVELS,
        key=lambda level: (-(raw_counts[level] - planned_counts[level]), BLOOM_LEVELS.index(level)),
    )
    for level in remainders[:remaining]:
        planned_counts = {**planned_counts, level: planned_counts[level] + 1}
    return planned_counts


def public_student_entry_url(evaluation_id: str) -> str:
    base_url = os.getenv("PUBLIC_STREAMLIT_BASE_URL", "http://localhost:8501").rstrip("/")
    query = urlencode({"mode": "student", "evaluation_id": evaluation_id})
    return f"{base_url}/?{query}"


def display_value(value: object) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "-"
    return str(value)


def query_param_value(name: str) -> str:
    value = st.query_params.get(name, "")
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value)


def init_state() -> None:
    initial_mode = "student" if query_param_value("mode") == "student" else "home"
    defaults = {
        "mode": initial_mode,
        "step": "join" if initial_mode == "student" else "manage",
        "evaluation": None,
        "admin_verified": False,
        "admin_password": "",
        "upload_result": None,
        "context": None,
        "questions": [],
        "joined_session": None,
        "report": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def reset_workspace() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


def call_api(action, *args):
    try:
        return action(*args)
    except ApiClientError as exc:
        render_api_error(exc)
        return None


def render_api_error(exc: ApiClientError) -> None:
    detail = exc.detail
    if isinstance(detail, dict):
        stage = detail.get("stage")
        reason = detail.get("reason")
        message = detail.get("message") or str(exc)
        st.error("진행 차단: FastAPI 요청이 실패했습니다.")
        if stage or reason:
            cols = st.columns(2)
            cols[0].metric("실패 단계", display_value(stage))
            cols[1].metric("실패 사유", display_value(reason))
        st.write(message)
        extra = {key: value for key, value in detail.items() if key not in {"stage", "reason", "message"}}
        if extra:
            with st.expander("상세 오류 정보"):
                st.json(extra)
        return
    if isinstance(detail, list):
        st.error("진행 차단: FastAPI 요청 검증에 실패했습니다.")
        with st.expander("검증 오류 상세", expanded=True):
            st.json(detail)
        return
    st.error(str(exc))


def set_mode(mode: str) -> None:
    st.session_state["mode"] = mode
    st.session_state["step"] = "manage" if mode == "professor" else "join"
    st.session_state["admin_verified"] = False
    st.session_state["admin_password"] = ""
    st.session_state["joined_session"] = None
    st.session_state["report"] = None
    st.rerun()


def show_artifact_breakdown(upload_result: dict[str, object]) -> None:
    reason_counts = upload_result.get("reason_counts", {})
    if not isinstance(reason_counts, dict):
        reason_counts = {}
    metrics = [
        ("추출 성공", upload_result.get("accepted_count", reason_counts.get("accepted", 0))),
        ("무시됨", upload_result.get("ignored_count", reason_counts.get("ignored", 0))),
        ("텍스트 없음", upload_result.get("empty_text_count", reason_counts.get("empty_text", 0))),
        ("용량 초과", upload_result.get("file_too_large_count", reason_counts.get("file_too_large", 0))),
        ("처리 제한", upload_result.get("processed_file_limit_count", reason_counts.get("processed_file_limit", 0))),
        ("실패", upload_result.get("failed_count", reason_counts.get("extract_failed", 0))),
    ]
    cols = st.columns(6)
    for col, (label, value) in zip(cols, metrics, strict=False):
        col.metric(label, int(value or 0))

    st.info(
        "파일 처리 상태는 zip 내부 파일을 추출/분류한 결과입니다. "
        "무시됨은 분석 대상이 아닌 경로 또는 확장자, 텍스트 없음은 추출 가능한 본문 부재, "
        "용량 초과는 파일별 처리 한도 초과, 처리 제한은 최대 처리 파일 수 도달, "
        "실패는 텍스트 추출 중 오류가 발생한 경우를 의미합니다."
    )

    processing_limits = upload_result.get("processing_limits", {})
    if not isinstance(processing_limits, dict):
        processing_limits = {}
    supported_extensions = upload_result.get("supported_extensions", [])
    if not isinstance(supported_extensions, list):
        supported_extensions = []

    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for artifact in upload_result.get("artifacts", []):
        if not isinstance(artifact, dict):
            continue
        metadata = artifact.get("metadata", {})
        reason = "accepted" if artifact.get("status") == "extracted" else "unknown"
        if isinstance(metadata, dict):
            reason = str(metadata.get("reason", reason))
        if reason == "accepted":
            continue
        grouped[reason].append(artifact)

    with st.expander("파일 처리 사유 예시"):
        if not grouped:
            st.caption("표시할 제외/실패 예시가 없습니다.")
        for reason, artifacts in sorted(grouped.items()):
            st.markdown(f"**{REASON_LABELS.get(reason, reason)}**")
            for artifact in artifacts[:8]:
                if not isinstance(artifact, dict):
                    continue
                st.markdown(f"- `{artifact.get('source_path', '-')}`")
                detail = processing_reason_detail(
                    artifact,
                    str(reason),
                    processing_limits,
                    supported_extensions,
                )
                if detail:
                    st.caption(detail)


def processing_reason_detail(
    artifact: dict[str, object],
    reason: str,
    processing_limits: dict[str, object],
    supported_extensions: list[object],
) -> str:
    metadata = artifact.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    if reason == "file_too_large":
        size = metadata.get("size")
        limit = (
            metadata.get("limit")
            or processing_limits.get("max_text_file_bytes")
            or processing_limits.get("max_text_file_size")
            or processing_limits.get("APP_MAX_TEXT_FILE_MB")
        )
        return f"실제 size={display_value(size)}, limit={display_value(limit)}"
    if reason == "unsupported_extension":
        extension = metadata.get("extension")
        supported = metadata.get("supported_extensions") or supported_extensions
        return (
            f"extension={display_value(extension)}, "
            f"supported_extensions={display_value(supported)}"
        )
    return ""


def render_rag_status(context: dict[str, object]) -> None:
    rag_status = context.get("rag_status", {})
    if not isinstance(rag_status, dict) or not rag_status:
        st.caption("RAG 상태 정보가 없습니다.")
        return
    st.subheader("RAG 인덱싱 상태")
    if rag_status.get("enabled") is False:
        st.error(f"진행 차단: RAG 비활성화 · {rag_status.get('reason', '-')}")
        return
    if rag_status.get("status") == "failed":
        st.error("진행 차단: RAG 인덱싱 실패")
        st.write(rag_status.get("message") or rag_status.get("reason") or "원인을 확인할 수 없습니다.")
        with st.expander("RAG 실패 상세"):
            st.json(rag_status)
        return
    cols = st.columns(5)
    cols[0].metric("상태", str(rag_status.get("status", "-")))
    cols[1].metric("전체 chunk", int(rag_status.get("inserted_count", 0) or 0))
    cols[2].metric("code chunk", int(rag_status.get("code_chunk_count", 0) or 0))
    cols[3].metric("document chunk", int(rag_status.get("document_chunk_count", 0) or 0))
    cols[4].metric("manifest", int(rag_status.get("manifest_chunk_count", 0) or 0))
    st.caption(
        f"collection={rag_status.get('collection_name', '-')} · embedding={rag_status.get('embedding_model', '-')}"
    )


def render_questions(questions: list[dict[str, object]]) -> None:
    st.subheader("생성 질문 검토 보드")
    st.caption("질문마다 Bloom 단계, 검증 의도, 기대 신호, 근거 파일을 한 화면에서 확인합니다.")
    for i, q in enumerate(questions):
        bloom_level = display_value(q.get("bloom_level"))
        difficulty = DIFFICULTY_LABELS.get(
            str(q.get("difficulty", "")), display_value(q.get("difficulty"))
        )
        refs = q.get("source_refs", [])
        grouped_refs = group_source_refs_by_path(refs) if isinstance(refs, list) else {}
        with st.container(border=True):
            header_cols = st.columns([0.7, 4.3, 1.2, 1.2])
            header_cols[0].markdown(f"### Q{i + 1}")
            header_cols[1].markdown(f"### {display_value(q.get('question'))}")
            header_cols[2].metric("Bloom", bloom_level)
            header_cols[3].metric("난이도", difficulty)

            signal_cols = st.columns([1, 1])
            with signal_cols[0]:
                st.markdown("**검증 의도**")
                st.write(display_value(q.get("intent")))
            with signal_cols[1]:
                st.markdown("**기대 답변 신호**")
                st.write(display_value(q.get("expected_signal")))

            st.markdown("**근거 파일 맵**")
            if grouped_refs:
                for path, path_refs in grouped_refs.items():
                    with st.expander(f"{path} · {len(path_refs)}개 근거", expanded=i == 0):
                        for ref in path_refs:
                            location = _ref_location(ref)
                            st.markdown(
                                f"- {location or '위치 정보 없음'} · "
                                f"{display_value(ref.get('artifact_role'))} / "
                                f"{display_value(ref.get('chunk_type'))}"
                            )
                            snippet = str(ref.get("snippet", "")).strip()
                            if snippet:
                                st.caption(snippet)
            else:
                st.caption("연결된 source ref가 없습니다.")


def group_source_refs_by_path(refs: list[object]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for ref in refs:
        if isinstance(ref, dict):
            grouped[str(ref.get("path", "-"))].append(ref)
    return dict(grouped)


def _ref_location(ref: dict[str, object]) -> str:
    if ref.get("line_start") and ref.get("line_end"):
        return f":L{ref['line_start']}-L{ref['line_end']}"
    if ref.get("page_or_slide"):
        return f" ({ref['page_or_slide']})"
    return ""


def render_professor() -> None:
    st.header("교수자: 방 만들기/관리")
    create_tab, manage_tab = st.tabs(["새 방 만들기", "기존 방 관리"])

    with create_tab:
        with st.form("create_room_form"):
            room_name = st.text_input("방/시험 이름", placeholder="예: 캡스톤 4조 프로젝트 검증")
            project_name = st.text_input("프로젝트명", placeholder="예: 프로젝트 수행 진위 평가 서비스")
            candidate_name = st.text_input("지원자/팀 라벨", placeholder="예: 4조", value="")
            description = st.text_area("프로젝트 설명", placeholder="핵심 기능과 제출 자료 범위를 간단히 입력하세요.")
            room_password = st.text_input("학생 입장 비밀번호", type="password")
            admin_password = st.text_input("관리자 비밀번호", type="password")
            uploaded_file = st.file_uploader("프로젝트 자료 zip", type=["zip"])
            st.markdown("#### 질문 생성 정책")
            total_questions = st.number_input("총 문항 수", min_value=3, max_value=12, value=6, step=1)
            ratio_cols = st.columns(3)
            bloom_ratios = {}
            for index, level in enumerate(BLOOM_LEVELS):
                bloom_ratios[level] = ratio_cols[index % 3].slider(
                    f"{level} 비율",
                    min_value=0,
                    max_value=10,
                    value=1,
                    step=1,
                )
            planned_counts = calculate_bloom_distribution(int(total_questions), bloom_ratios)
            if sum(bloom_ratios.values()) == 0:
                st.warning("Bloom 비율이 모두 0입니다. 하나 이상의 단계 비율을 1 이상으로 설정하세요.")
            else:
                st.caption("예정 문항 수는 floor 배분 후 남은 문항을 큰 소수점 순으로 배정합니다. 동률은 Bloom 순서를 따릅니다.")
                st.dataframe(
                    [
                        {
                            "Bloom 단계": level,
                            "비율": bloom_ratios[level],
                            "예정 문항 수": planned_counts[level],
                        }
                        for level in BLOOM_LEVELS
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
            submitted = st.form_submit_button("방 생성하고 zip 업로드", type="primary")

        if submitted:
            if not project_name or not room_password or not admin_password or uploaded_file is None:
                st.warning("프로젝트명, 비밀번호, 관리자 비밀번호, zip 파일을 모두 입력하세요.")
            elif sum(bloom_ratios.values()) == 0:
                st.warning("Bloom 비율이 모두 0이면 방을 만들 수 없습니다.")
            else:
                question_policy = {
                    "total_questions": int(total_questions),
                    "bloom_ratios": bloom_ratios,
                    "planned_counts": planned_counts,
                    "allocation_rule": "largest_remainder",
                }
                with st.spinner("방을 만들고 zip 자료를 업로드하는 중입니다..."):
                    evaluation = call_api(
                        create_evaluation,
                        project_name,
                        candidate_name,
                        description,
                        room_name or project_name,
                        room_password,
                        admin_password,
                        question_policy,
                    )
                    if evaluation:
                        upload_result = call_api(
                            upload_zip,
                            evaluation["id"],
                            uploaded_file.name,
                            uploaded_file,
                            admin_password,
                        )
                        if upload_result:
                            st.session_state["evaluation"] = evaluation
                            st.session_state["upload_result"] = upload_result
                            st.session_state["admin_verified"] = True
                            st.session_state["admin_password"] = admin_password
                            st.success(f"방 생성 완료 · 평가 ID: {evaluation['id']}")
                            st.rerun()

    with manage_tab:
        with st.form("admin_verify_form"):
            evaluation_id = st.text_input("평가/방 ID")
            admin_password = st.text_input("관리자 비밀번호", type="password", key="admin_verify_password")
            submitted = st.form_submit_button("관리자 확인")
        if submitted:
            if not evaluation_id or not admin_password:
                st.warning("평가 ID와 관리자 비밀번호를 입력하세요.")
            else:
                verified = call_api(verify_admin, evaluation_id, admin_password)
                if verified:
                    st.session_state["evaluation"] = {"id": evaluation_id}
                    st.session_state["admin_verified"] = True
                    st.session_state["admin_password"] = admin_password
                    st.success("관리자 확인 완료")
                    st.rerun()

    if not st.session_state.get("admin_verified") or not st.session_state.get("evaluation"):
        return

    evaluation = st.session_state["evaluation"]
    evaluation_id = str(evaluation["id"])
    student_url = public_student_entry_url(evaluation_id)
    admin_password = str(st.session_state.get("admin_password", ""))
    upload_result = st.session_state.get("upload_result")
    st.divider()
    st.subheader("방 관리")
    st.success("방 생성과 zip 업로드가 완료되었습니다." if upload_result else "관리자 확인이 완료되었습니다.")
    col1, col2 = st.columns([1, 2])
    col1.metric("평가 ID", evaluation_id)
    with col2:
        st.markdown("**학생 입장 URL 전체**")
        st.code(student_url, language=None)
    st.info(
        "학생에게 위 학생 입장 URL, 평가 ID, 방 비밀번호를 함께 전달하세요. "
        "학생은 공용 입장 화면에서 평가 ID와 방 비밀번호로 로그인 없이 입장합니다."
    )

    if isinstance(upload_result, dict):
        show_artifact_breakdown(upload_result)
    else:
        st.caption("기존 방은 현재 화면에서 업로드 결과를 다시 불러오지 않습니다. 분석/질문 생성은 계속 진행할 수 있습니다.")

    if st.button("context 생성 및 질문 만들기", type="primary"):
        with st.spinner("자료를 요약하고 질문을 생성하는 중입니다..."):
            context = call_api(extract_evaluation, evaluation_id, admin_password)
            if context:
                st.session_state["context"] = context
                questions = call_api(generate_questions, evaluation_id, admin_password)
                if questions:
                    st.session_state["questions"] = questions
                    st.success("질문 생성 완료")
                else:
                    st.session_state["questions"] = []
                st.rerun()

    if st.session_state.get("context"):
        ctx = st.session_state["context"]
        st.subheader("분석 요약")
        st.write(ctx.get("summary"))
        render_rag_status(ctx)
        col1, col2 = st.columns(2)
        with col1:
            with st.expander("기술 스택"):
                for item in ctx.get("tech_stack", []):
                    st.markdown(f"- {item}")
            with st.expander("주요 기능"):
                for item in ctx.get("features", []):
                    st.markdown(f"- {item}")
        with col2:
            with st.expander("프로젝트 영역"):
                for area in ctx.get("areas", []):
                    st.markdown(f"**{area.get('name', '-')}** — {area.get('summary', '-')}")
            with st.expander("리스크 포인트"):
                for item in ctx.get("risk_points", []):
                    st.markdown(f"- {item}")

    questions = st.session_state.get("questions", [])
    if isinstance(questions, list) and questions:
        render_questions(questions)

    if st.button("최신 리포트 확인"):
        with st.spinner("리포트를 불러오는 중..."):
            report = call_api(get_latest_report, evaluation_id, admin_password)
            if report:
                st.session_state["report"] = report
                st.rerun()

    if st.session_state.get("report"):
        render_report(st.session_state["report"])


def render_student() -> None:
    st.header("학생/지원자: 방 입장")
    with st.form("join_room_form"):
        evaluation_id = st.text_input("평가/방 ID", value=query_param_value("evaluation_id"))
        participant_name = st.text_input("이름/팀명", placeholder="예: 홍길동 또는 4조")
        room_password = st.text_input("방 비밀번호", type="password")
        submitted = st.form_submit_button("입장", type="primary")

    if submitted:
        if not evaluation_id or not participant_name or not room_password:
            st.warning("평가 ID, 이름/팀명, 방 비밀번호를 모두 입력하세요.")
        else:
            joined = call_api(join_evaluation, evaluation_id, participant_name, room_password)
            if joined:
                st.session_state["joined_session"] = joined
                st.success("입장 완료")
                st.rerun()

    joined = st.session_state.get("joined_session")
    if isinstance(joined, dict):
        session = joined.get("session", {})
        evaluation = joined.get("evaluation", {})
        path = str(joined.get("interview_url_path", ""))
        interview_url = f"{get_api_base_url()}{path}"
        st.subheader("단계형 프로젝트 인터뷰")
        st.caption(f"방: {evaluation.get('room_name', evaluation.get('project_name', '-'))}")
        st.success(f"세션 준비 완료 · 세션 ID: {session.get('id', '-')}")
        session_token = str(session.get("session_token", ""))
        if session_token:
            st.code(session_token, language=None)
        st.info("아래 버튼을 클릭한 뒤 표시된 세션 토큰을 한 번 입력하면 단계형 인터뷰가 시작됩니다.")
        st.link_button("단계형 인터뷰 시작", interview_url, type="primary")


def render_report(report: dict[str, object]) -> None:
    st.header("최종 리포트")
    col1, col2 = st.columns(2)
    col1.metric("최종 판정", report["final_decision"])
    col2.metric("신뢰도 점수", report["authenticity_score"])
    st.subheader("요약")
    st.write(report["summary"])
    st.subheader("프로젝트 영역별 신뢰도")
    st.dataframe(report.get("area_analyses", []), use_container_width=True)
    st.subheader("질문별 평가")
    st.dataframe(report.get("question_evaluations", []), use_container_width=True)
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("강점")
        st.write(report.get("strengths", []))
        st.subheader("근거 일치")
        st.write(report.get("evidence_alignment", []))
    with col2:
        st.subheader("의심 지점")
        st.write(report.get("suspicious_points", []))
        st.subheader("추가 확인 질문")
        st.write(report.get("recommended_followups", []))


init_state()

st.title("프로젝트 수행 진위 평가")
st.caption("자료 기반 질문으로 지원자가 프로젝트를 진짜 수행했는지 검증합니다.")

with st.sidebar:
    st.subheader("API 상태")
    try:
        health = get_health()
    except ApiClientError as exc:
        st.warning(str(exc))
        st.caption("FastAPI 서버: `uv run uvicorn services.api.app.main:app --reload`")
    else:
        st.success("연결됨")
        storage = health.get("storage", {})
        if isinstance(storage, dict):
            st.caption(f"SQLite: {storage.get('sqlite_path', '-')}")

    st.divider()
    if st.button("처음부터 다시 시작"):
        reset_workspace()

mode = st.session_state["mode"]
if mode == "home":
    st.header("시작")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("교수자")
        st.write("방을 만들고 zip 자료를 업로드한 뒤, 자료 기반 질문과 리포트를 관리합니다.")
        if st.button("교수자: 방 만들기/관리", type="primary", use_container_width=True):
            set_mode("professor")
    with col2:
        st.subheader("학생/지원자")
        st.write("평가 ID와 방 비밀번호로 입장해 실시간 음성 인터뷰를 진행합니다.")
        if st.button("학생: 방 입장", use_container_width=True):
            set_mode("student")
elif mode == "professor":
    if st.button("시작 화면으로 돌아가기"):
        set_mode("home")
    render_professor()
elif mode == "student":
    if st.button("시작 화면으로 돌아가기"):
        set_mode("home")
    render_student()
