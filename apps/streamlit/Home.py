import os
import sys
from collections import Counter, defaultdict
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
    get_context,
    get_evaluation_status,
    get_health,
    get_latest_report,
    join_evaluation,
    list_questions,
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
        "evaluation_status": None,
        "question_generation_event": None,
        "question_generation_error": None,
        "last_operation": "",
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


def call_api_capture_error(action, *args) -> tuple[object | None, ApiClientError | None]:
    try:
        return action(*args), None
    except ApiClientError as exc:
        return None, exc


def persist_question_generation_error(evaluation_id: str, exc: ApiClientError) -> None:
    detail = exc.detail
    st.session_state["question_generation_error"] = {
        "evaluation_id": evaluation_id,
        "message": str(exc),
        "detail": detail,
    }


def clear_question_generation_error() -> None:
    st.session_state["question_generation_event"] = None
    st.session_state["question_generation_error"] = None


def render_persisted_generation_error(evaluation_id: str) -> None:
    error = st.session_state.get("question_generation_error")
    if not isinstance(error, dict) or error.get("evaluation_id") != evaluation_id:
        return
    detail = error.get("detail")
    st.error("질문 생성 API 요청이 실패했습니다.")
    if isinstance(detail, dict):
        stage = detail.get("stage")
        reason = detail.get("reason")
        message = detail.get("message") or error.get("message")
        cols = st.columns(2)
        cols[0].metric("실패 단계", display_value(stage))
        cols[1].metric("실패 사유", display_value(reason))
        st.write(message)
        check_targets = detail.get("check_targets", [])
        if isinstance(check_targets, list) and check_targets:
            st.markdown("**확인 대상**")
            for target in check_targets:
                st.markdown(f"- {target}")
        extra = {key: value for key, value in detail.items() if key not in {"stage", "reason", "message", "check_targets"}}
        if extra:
            with st.expander("질문 생성 실패 상세"):
                st.json(extra)
        return
    if isinstance(detail, list):
        with st.expander("질문 생성 검증 오류", expanded=True):
            st.json(detail)
        return
    st.write(display_value(error.get("message")))


def fetch_api(action, *args) -> object | None:
    try:
        return action(*args)
    except ApiClientError as exc:
        st.session_state["last_operation"] = str(exc)
        return None


def refresh_professor_state(evaluation_id: str, admin_password: str) -> dict[str, object] | None:
    st.session_state["last_operation"] = ""
    st.session_state["evaluation_status"] = None
    st.session_state["context"] = None
    st.session_state["questions"] = []
    status = fetch_api(get_evaluation_status, evaluation_id, admin_password)
    if not isinstance(status, dict):
        return None
    st.session_state["evaluation_status"] = status
    if bool(status.get("has_context")):
        context = fetch_api(get_context, evaluation_id, admin_password)
        if isinstance(context, dict):
            st.session_state["context"] = context
    if int(status.get("question_count", 0) or 0) > 0:
        questions = fetch_api(list_questions, evaluation_id, admin_password)
        st.session_state["questions"] = questions if isinstance(questions, list) else []
    return status


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


def render_status_console(status: dict[str, object] | None) -> None:
    if not isinstance(status, dict):
        st.info("상태를 아직 불러오지 않았습니다. 방 생성 또는 관리자 확인 후 상태를 새로고침하세요.")
        return
    phase = str(status.get("phase", "-"))
    can_join = bool(status.get("can_join"))
    questions_ready = bool(status.get("questions_ready"))
    message = display_value(status.get("user_message"))
    if can_join:
        st.success(message)
    elif bool(status.get("retryable")):
        st.info(message)
    else:
        st.warning(message)

    rag_status = status.get("rag_status", {})
    rag_text = "-"
    if isinstance(rag_status, dict):
        rag_text = str(rag_status.get("status") or rag_status.get("reason") or "-")
    cols = st.columns(5)
    cols[0].metric("현재 단계", phase)
    cols[1].metric("저장 질문", int(status.get("question_count", 0) or 0))
    cols[2].metric("기대 질문", int(status.get("expected_question_count", 0) or 0))
    cols[3].metric("RAG", rag_text)
    cols[4].metric("입장 가능", "가능" if questions_ready and can_join else "대기")

    blocked_reason = str(status.get("blocked_reason", ""))
    check_targets = status.get("check_targets", [])
    if blocked_reason or check_targets:
        with st.expander("상태 판단 근거"):
            if blocked_reason:
                st.markdown(f"**차단 사유:** `{blocked_reason}`")
            if isinstance(check_targets, list) and check_targets:
                st.markdown("**확인 대상**")
                for target in check_targets:
                    st.markdown(f"- {target}")


def render_question_console(questions: list[dict[str, object]], status: dict[str, object] | None) -> None:
    st.subheader("Evidence Console")
    st.caption("질문 생성 여부와 각 질문의 코드·문서 근거를 한 번에 검토합니다.")
    render_status_console(status)
    if not questions:
        render_question_empty_state(status)
        return

    overview_rows = []
    bloom_counts: Counter[str] = Counter()
    difficulty_counts: Counter[str] = Counter()
    source_paths = set()
    for index, question in enumerate(questions, start=1):
        refs = question.get("source_refs", [])
        refs_list = refs if isinstance(refs, list) else []
        grouped_refs = group_source_refs_by_path(refs_list)
        code_refs = [ref for ref in refs_list if _is_code_ref(ref)]
        doc_refs = [ref for ref in refs_list if _is_document_ref(ref)]
        bloom_level = display_value(question.get("bloom_level"))
        difficulty = DIFFICULTY_LABELS.get(
            str(question.get("difficulty", "")), display_value(question.get("difficulty"))
        )
        bloom_counts[bloom_level] += 1
        difficulty_counts[difficulty] += 1
        source_paths.update(grouped_refs.keys())
        overview_rows.append(
            {
                "Q": index,
                "Bloom": bloom_level,
                "난이도": difficulty,
                "검증 초점": display_value(question.get("verification_focus")),
                "근거 수": len(refs_list),
                "code refs": len(code_refs),
                "doc refs": len(doc_refs),
            }
        )

    metric_cols = st.columns(4)
    metric_cols[0].metric("질문 수", len(questions))
    metric_cols[1].metric("Bloom 커버리지", f"{len([k for k, v in bloom_counts.items() if v])}/6")
    metric_cols[2].metric("근거 파일", len(source_paths))
    metric_cols[3].metric("문서-코드 근거", "확보" if all(row["code refs"] and row["doc refs"] for row in overview_rows) else "확인 필요")

    left, right = st.columns([0.9, 1.6])
    with left:
        st.markdown("#### 단계 rail")
        for phase, label in [
            ("created", "방 생성"),
            ("uploaded", "자료 업로드"),
            ("context_ready", "분석 완료"),
            ("questions_ready", "질문 저장"),
        ]:
            marker = "●" if isinstance(status, dict) and status.get("phase") == phase else "○"
            st.markdown(f"{marker} **{label}** `{phase}`")
        st.markdown("#### Bloom 분포")
        st.dataframe(
            [{"Bloom": level, "문항 수": bloom_counts.get(level, 0)} for level in BLOOM_LEVELS],
            hide_index=True,
            width="stretch",
        )
        st.markdown("#### 난이도 분포")
        st.dataframe(
            [{"난이도": key, "문항 수": value} for key, value in difficulty_counts.items()],
            hide_index=True,
            width="stretch",
        )
    with right:
        st.markdown("#### 질문 overview")
        st.dataframe(overview_rows, hide_index=True, width="stretch")
        selected = st.radio(
            "질문 dossier 선택",
            options=list(range(len(questions))),
            format_func=lambda index: f"Q{index + 1} · {display_value(questions[index].get('bloom_level'))}",
            horizontal=True,
        )
        render_question_dossier(questions[int(selected)], int(selected) + 1)


def render_question_empty_state(status: dict[str, object] | None) -> None:
    if not isinstance(status, dict):
        st.info("관리자 확인 후 DB 기준 질문 상태를 조회합니다.")
        return
    phase = str(status.get("phase", ""))
    if phase == "created":
        st.warning("아직 zip 자료가 업로드되지 않아 질문을 만들 수 없습니다.")
    elif phase == "uploaded":
        st.info("자료 업로드는 완료됐습니다. context 생성 및 질문 만들기 버튼으로 분석을 시작하세요.")
    elif phase in {"rag_not_ready", "indexing_failed"}:
        st.error(display_value(status.get("user_message")))
    elif phase == "context_ready":
        st.info("분석은 완료됐지만 아직 저장된 질문이 없습니다. 질문 생성을 실행하세요.")
    else:
        st.warning("DB에서 저장된 질문을 찾지 못했습니다. 상태를 새로고침하거나 질문 생성을 다시 실행하세요.")


def render_question_dossier(question: dict[str, object], index: int) -> None:
    st.markdown(f"#### Q{index}. {display_value(question.get('question'))}")
    detail_cols = st.columns(2)
    with detail_cols[0]:
        st.markdown("**검증 의도**")
        st.write(display_value(question.get("intent")))
        st.markdown("**검증 초점**")
        st.write(display_value(question.get("verification_focus")))
    with detail_cols[1]:
        st.markdown("**기대 답변 신호**")
        st.write(display_value(question.get("expected_signal")))
        st.markdown("**기대 근거**")
        st.write(display_value(question.get("expected_evidence")))
    st.markdown("**Source ref 요구사항**")
    st.caption(display_value(question.get("source_ref_requirements")))

    refs = question.get("source_refs", [])
    grouped_refs = group_source_refs_by_path(refs if isinstance(refs, list) else [])
    st.markdown("**근거 파일 맵**")
    if not grouped_refs:
        st.caption("연결된 source ref가 없습니다.")
        return
    for path, path_refs in grouped_refs.items():
        with st.expander(f"{path} · {len(path_refs)}개 근거", expanded=False):
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


def _is_code_ref(ref: object) -> bool:
    if not isinstance(ref, dict):
        return False
    return str(ref.get("artifact_role", "")) in {
        "codebase_source",
        "codebase_test",
        "codebase_config",
        "codebase_api_spec",
    }


def _is_document_ref(ref: object) -> bool:
    if not isinstance(ref, dict):
        return False
    role = str(ref.get("artifact_role", ""))
    return role == "codebase_overview" or role.startswith("project_")


def render_professor() -> None:
    st.header("교수자: 방 만들기/관리")
    create_tab, manage_tab = st.tabs(["새 방 만들기", "기존 방 관리"])

    with create_tab:
        st.markdown("#### 질문 생성 정책")
        total_questions = st.slider(
            "총 문항 수",
            min_value=1,
            max_value=20,
            value=6,
            step=1,
            key="create_room_total_questions",
        )
        ratio_cols = st.columns(3)
        bloom_ratios = {}
        for index, level in enumerate(BLOOM_LEVELS):
            bloom_ratios[level] = ratio_cols[index % 3].slider(
                f"{level} 비율",
                min_value=0,
                max_value=10,
                value=1,
                step=1,
                key=f"create_room_bloom_ratio_{level}",
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
                width="stretch",
            )

        with st.form("create_room_form"):
            room_name = st.text_input("방/시험 이름", placeholder="예: 캡스톤 4조 프로젝트 검증")
            project_name = st.text_input("프로젝트명", placeholder="예: 프로젝트 수행 진위 평가 서비스")
            candidate_name = st.text_input("지원자/팀 라벨", placeholder="예: 4조", value="")
            description = st.text_area("프로젝트 설명", placeholder="핵심 기능과 제출 자료 범위를 간단히 입력하세요.")
            room_password = st.text_input("학생 입장 비밀번호", type="password")
            admin_password = st.text_input("관리자 비밀번호", type="password")
            uploaded_file = st.file_uploader("프로젝트 자료 zip", type=["zip"])
            submitted = st.form_submit_button("방 생성하고 zip 업로드", type="primary")

        if submitted:
            if not project_name or not room_password or not admin_password or uploaded_file is None:
                st.warning("프로젝트명, 비밀번호, 관리자 비밀번호, zip 파일을 모두 입력하세요.")
            elif sum(bloom_ratios.values()) == 0:
                st.warning("Bloom 비율이 모두 0이면 방을 만들 수 없습니다.")
            else:
                question_policy = {
                    "total_question_count": int(total_questions),
                    "bloom_ratios": bloom_ratios,
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
                            clear_question_generation_error()
                            st.session_state["evaluation"] = evaluation
                            st.session_state["upload_result"] = upload_result
                            st.session_state["admin_verified"] = True
                            st.session_state["admin_password"] = admin_password
                            refresh_professor_state(str(evaluation["id"]), admin_password)
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
                    clear_question_generation_error()
                    st.session_state["evaluation"] = {"id": evaluation_id}
                    st.session_state["admin_verified"] = True
                    st.session_state["admin_password"] = admin_password
                    refresh_professor_state(evaluation_id, admin_password)
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
        st.caption("기존 방은 업로드 결과 요약은 복구하지 않지만, DB 기준 status/context/questions는 다시 불러옵니다.")

    if st.button("상태 새로고침", width="stretch"):
        refresh_professor_state(evaluation_id, admin_password)
        st.rerun()

    status = st.session_state.get("evaluation_status")
    last_operation = st.session_state.get("last_operation")
    if last_operation:
        st.warning(str(last_operation))

    if st.button("context 생성 및 질문 만들기", type="primary"):
        with st.spinner("자료를 요약하고 질문을 생성하는 중입니다..."):
            clear_question_generation_error()
            status_before = refresh_professor_state(evaluation_id, admin_password)
            phase_before = (
                str(status_before.get("phase", "")) if isinstance(status_before, dict) else ""
            )

            if phase_before == "questions_ready":
                st.session_state["question_generation_event"] = (
                    "질문이 이미 DB에 저장되어 있어 기존 결과를 그대로 표시합니다."
                )
            elif not isinstance(status_before, dict):
                st.session_state["question_generation_event"] = (
                    "현재 DB 상태를 확인하지 못했습니다. 상태 새로고침 후 다시 시도하세요."
                )
            else:
                if not bool(status_before.get("has_context")):
                    context = call_api(extract_evaluation, evaluation_id, admin_password)
                    if context:
                        st.session_state["context"] = context

                status_after_extract = refresh_professor_state(evaluation_id, admin_password)
                phase_after_extract = (
                    str(status_after_extract.get("phase", ""))
                    if isinstance(status_after_extract, dict)
                    else ""
                )

                if phase_after_extract == "questions_ready":
                    st.session_state["question_generation_event"] = (
                        "질문이 이미 DB에 저장되어 있어 기존 결과를 그대로 표시합니다."
                    )
                elif phase_after_extract == "context_ready":
                    questions, question_error = call_api_capture_error(
                        generate_questions, evaluation_id, admin_password
                    )
                    if question_error is not None:
                        status_after_error = refresh_professor_state(
                            evaluation_id, admin_password
                        )
                        phase_after_error = (
                            str(status_after_error.get("phase", ""))
                            if isinstance(status_after_error, dict)
                            else ""
                        )
                        if phase_after_error == "questions_ready":
                            st.session_state["question_generation_error"] = None
                            st.session_state["question_generation_event"] = (
                                "질문 생성 응답은 지연됐지만 DB에는 질문이 저장되었습니다. DB 기준 결과를 표시합니다."
                            )
                        else:
                            persist_question_generation_error(
                                evaluation_id, question_error
                            )
                            st.session_state["question_generation_event"] = (
                                "질문 생성 API 요청이 실패했습니다. 아래 실패 단계와 확인 대상을 확인하세요."
                            )
                    elif isinstance(questions, list) and not questions:
                        st.session_state["question_generation_event"] = (
                            "질문 생성 요청은 끝났지만 응답 질문 수가 0개입니다."
                        )
                        st.session_state["questions"] = []
                    elif isinstance(questions, list):
                        st.session_state["question_generation_event"] = (
                            f"질문 생성 응답 {len(questions)}개를 받았습니다. DB 기준으로 다시 조회했습니다."
                        )
                elif isinstance(status_after_extract, dict):
                    st.session_state["question_generation_event"] = str(
                        status_after_extract.get("user_message")
                        or "질문 생성 전 상태를 먼저 확인하세요."
                    )
            refresh_professor_state(evaluation_id, admin_password)
            st.rerun()

    generation_event = st.session_state.get("question_generation_event")
    if generation_event:
        st.caption(str(generation_event))
    render_persisted_generation_error(evaluation_id)

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
    status = st.session_state.get("evaluation_status")
    render_question_console(
        questions if isinstance(questions, list) else [],
        status if isinstance(status, dict) else None,
    )

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
        st.subheader("음성 프로젝트 인터뷰")
        st.caption(f"방: {evaluation.get('room_name', evaluation.get('project_name', '-'))}")
        st.success(f"세션 준비 완료 · 세션 ID: {session.get('id', '-')}")
        st.link_button("음성 인터뷰 시작", interview_url, type="primary")


def render_report(report: dict[str, object]) -> None:
    st.header("최종 리포트")
    col1, col2 = st.columns(2)
    col1.metric("최종 판정", report["final_decision"])
    col2.metric("신뢰도 점수", report["authenticity_score"])
    st.subheader("요약")
    st.write(report["summary"])
    st.subheader("프로젝트 영역별 신뢰도")
    st.dataframe(report.get("area_analyses", []), width="stretch")
    st.subheader("질문별 평가")
    st.dataframe(report.get("question_evaluations", []), width="stretch")
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
        if st.button("교수자: 방 만들기/관리", type="primary", width="stretch"):
            set_mode("professor")
    with col2:
        st.subheader("학생/지원자")
        st.write("평가 ID와 방 비밀번호로 입장해 실시간 음성 인터뷰를 진행합니다.")
        if st.button("학생: 방 입장", width="stretch"):
            set_mode("student")
elif mode == "professor":
    if st.button("시작 화면으로 돌아가기"):
        set_mode("home")
    render_professor()
elif mode == "student":
    if st.button("시작 화면으로 돌아가기"):
        set_mode("home")
    render_student()
