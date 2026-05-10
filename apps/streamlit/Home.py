import sys
from collections import defaultdict
from pathlib import Path

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

REASON_LABELS = {
    "accepted": "추출 성공",
    "ignored": "무시됨",
    "empty_text": "텍스트 없음",
    "file_too_large": "용량 초과",
    "processed_file_limit": "처리 제한",
    "extract_failed": "실패",
}


def init_state() -> None:
    defaults = {
        "mode": "home",
        "step": "manage",
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
        st.error(str(exc))
        return None


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

    grouped: dict[str, list[str]] = defaultdict(list)
    for artifact in upload_result.get("artifacts", []):
        if not isinstance(artifact, dict):
            continue
        metadata = artifact.get("metadata", {})
        reason = "accepted" if artifact.get("status") == "extracted" else "unknown"
        if isinstance(metadata, dict):
            reason = str(metadata.get("reason", reason))
        grouped[reason].append(str(artifact.get("source_path", "-")))

    with st.expander("파일 처리 사유 예시"):
        for reason, paths in sorted(grouped.items()):
            st.markdown(f"**{REASON_LABELS.get(reason, reason)}**")
            for path in paths[:8]:
                st.markdown(f"- `{path}`")


def render_questions(questions: list[dict[str, object]]) -> None:
    with st.expander("생성된 질문과 source refs", expanded=True):
        for i, q in enumerate(questions):
            st.markdown(f"**Q{i + 1}** ({q.get('bloom_level', '-')}) — {q.get('question', '-')}")
            refs = q.get("source_refs", [])
            if isinstance(refs, list) and refs:
                ref_paths = [str(ref.get("path", "-")) for ref in refs if isinstance(ref, dict)]
                st.caption("근거: " + ", ".join(ref_paths[:3]))


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
            submitted = st.form_submit_button("방 생성하고 zip 업로드", type="primary")

        if submitted:
            if not project_name or not room_password or not admin_password or uploaded_file is None:
                st.warning("프로젝트명, 비밀번호, 관리자 비밀번호, zip 파일을 모두 입력하세요.")
            else:
                with st.spinner("방을 만들고 zip 자료를 업로드하는 중입니다..."):
                    evaluation = call_api(
                        create_evaluation,
                        project_name,
                        candidate_name,
                        description,
                        room_name or project_name,
                        room_password,
                        admin_password,
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
    admin_password = str(st.session_state.get("admin_password", ""))
    st.divider()
    st.subheader("방 관리")
    st.caption(f"평가 ID: `{evaluation_id}`")
    st.info("학생에게 평가 ID와 방 비밀번호를 전달하세요. 학생은 로그인 없이 입장합니다.")

    upload_result = st.session_state.get("upload_result")
    if isinstance(upload_result, dict):
        show_artifact_breakdown(upload_result)
    else:
        st.caption("기존 방은 현재 화면에서 업로드 결과를 다시 불러오지 않습니다. 분석/질문 생성은 계속 진행할 수 있습니다.")

    if st.button("context 생성 및 질문 만들기", type="primary"):
        with st.spinner("자료를 요약하고 질문을 생성하는 중입니다..."):
            context = call_api(extract_evaluation, evaluation_id, admin_password)
            questions = call_api(generate_questions, evaluation_id, admin_password)
            if context and questions:
                st.session_state["context"] = context
                st.session_state["questions"] = questions
                st.success("질문 생성 완료")
                st.rerun()

    if st.session_state.get("context"):
        ctx = st.session_state["context"]
        st.subheader("분석 요약")
        st.write(ctx.get("summary"))
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
        evaluation_id = st.text_input("평가/방 ID")
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
        st.subheader("실시간 음성 인터뷰")
        st.caption(f"방: {evaluation.get('room_name', evaluation.get('project_name', '-'))}")
        st.success(f"세션 준비 완료 · 세션 ID: {session.get('id', '-')}")
        st.info("아래 버튼을 클릭하면 새 탭에서 기존 마이크 권한 기반 실시간 인터뷰가 시작됩니다.")
        st.link_button("실시간 음성 인터뷰 시작", interview_url, type="primary")


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
