from __future__ import annotations

import asyncio
import base64
import json

import pytest
from fastapi.testclient import TestClient

from services.api.app.main import app
from services.api.app.project_evaluations.interview.intent_classifier import (
    StudentIntent,
    classify_student_intent,
    is_decline_response,
)
from services.api.app.project_evaluations.router_realtime import _HTML
from services.api.app.project_evaluations.realtime.controller import (
    RealtimeInterviewController,
    RealtimeInterviewState,
)
from services.api.app.project_evaluations.realtime.proxy import (
    RealtimeServerTimeouts,
    _browser_to_oai,
    _configure_session,
    _create_audio_response,
    _oai_to_browser,
)
from services.api.tests.realtime_test_utils import (
    FakeBrowserWebSocket,
    FakeLlm,
    FakeOaiWebSocket,
)


@pytest.fixture()
def questions() -> list[dict[str, str]]:
    return [
        {"question": "첫 번째 질문", "intent": "구현 이해"},
        {"question": "두 번째 질문", "intent": "설계 이해"},
    ]


def test_realtime_session_update_uses_live_compatible_payload_contract() -> None:
    async def run_case() -> list[dict]:
        oai_ws = FakeOaiWebSocket([{"type": "session.updated"}])

        await _configure_session(oai_ws, "인터뷰 지침", model="gpt-realtime-1.5")

        return oai_ws.sent

    sent = asyncio.run(run_case())

    assert len(sent) == 1
    payload = sent[0]
    session = payload["session"]
    assert payload["type"] == "session.update"
    assert session["instructions"] == "인터뷰 지침"
    assert session["modalities"] == ["audio"]
    assert session["voice"] == "coral"
    assert session["input_audio_format"] == "pcm16"
    assert session["output_audio_format"] == "pcm16"
    assert session["input_audio_transcription"] == {"model": "whisper-1"}
    assert session["turn_detection"] == {
        "type": "server_vad",
        "create_response": False,
        "prefix_padding_ms": 300,
        "silence_duration_ms": 800,
    }
    assert "output_modalities" not in session
    assert "audio" not in session
    assert "model" not in session


def test_realtime_response_create_uses_live_compatible_payload_contract() -> None:
    async def run_case() -> list[dict]:
        oai_ws = FakeOaiWebSocket()

        await _create_audio_response(oai_ws, "오프닝만 말하세요")

        return oai_ws.sent

    sent = asyncio.run(run_case())

    assert sent == [
        {
            "type": "response.create",
            "response": {
                "modalities": ["audio"],
                "instructions": "오프닝만 말하세요",
            },
        }
    ]
    assert "output_modalities" not in sent[0]["response"]
    assert "audio" not in sent[0]["response"]


def test_realtime_session_update_requires_session_updated() -> None:
    async def run_case() -> None:
        oai_ws = FakeOaiWebSocket([])

        await _configure_session(oai_ws, "인터뷰 지침", session_update_timeout=0.01)

    with pytest.raises(RuntimeError, match="session.updated"):
        asyncio.run(run_case())


def test_realtime_session_update_preserves_openai_error_details() -> None:
    async def run_case() -> None:
        oai_ws = FakeOaiWebSocket(
            [
                {
                    "type": "error",
                    "error": {
                        "message": "Unknown parameter: 'session.output_modalities'.",
                        "code": "unknown_parameter",
                        "param": "session.output_modalities",
                    },
                }
            ]
        )

        await _configure_session(oai_ws, "인터뷰 지침")

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(run_case())

    message = str(exc_info.value)
    assert "Unknown parameter" in message
    assert "session.output_modalities" in message
    assert "unknown_parameter" in message


def test_student_intent_uses_llm_output() -> None:
    llm = FakeLlm("skip")

    assert classify_student_intent("넘어갈게요", llm) == StudentIntent.SKIP
    assert llm.calls[0]["temperature"] == 0.0
    assert llm.calls[0]["max_tokens"] == 8


def test_decline_response_uses_llm_no() -> None:
    llm = FakeLlm("no")

    assert is_decline_response("추가로 설명하겠습니다", llm) is False


def test_decline_response_disabled_llm_fails_explicitly() -> None:
    llm = FakeLlm(enabled=False)

    with pytest.raises(RuntimeError, match="비활성화"):
        is_decline_response("없습니다", llm)


def test_oai_to_browser_accepts_recv_only_realtime_connection(
    questions: list[dict[str, str]],
) -> None:
    async def run_case() -> list[dict]:
        controller = RealtimeInterviewController(questions)
        browser_ws = FakeBrowserWebSocket([])
        oai_ws = FakeOaiWebSocket(
            [{"type": "response.audio.done"}, {"type": "response.done"}]
        )
        interview_ended = asyncio.Event()

        await _oai_to_browser(
            oai_ws,
            browser_ws,
            questions,
            interview_ended,
            controller,
            decline_llm=None,
        )

        return browser_ws.sent_json

    sent_json = asyncio.run(run_case())

    assert sent_json == [{"type": "response.audio.done"}, {"type": "response.done"}]


def test_empty_transcription_completion_clears_pending_timeout_block(
    questions: list[dict[str, str]],
) -> None:
    async def run_case() -> tuple[int, bool, list[dict]]:
        controller = RealtimeInterviewController(questions)
        controller.begin_opening()
        controller.handle_playback_done()
        controller.handle_user_transcript(
            "20201234 홍길동", intent=StudentIntent.ANSWER
        )
        controller.handle_playback_done()
        controller.handle_user_transcript("본문 답변", intent=StudentIntent.ANSWER)
        controller.handle_playback_done()
        controller.handle_input_committed()
        browser_ws = FakeBrowserWebSocket([])
        oai_ws = FakeOaiWebSocket(
            [
                {
                    "type": "conversation.item.input_audio_transcription.completed",
                    "transcript": "",
                }
            ]
        )
        interview_ended = asyncio.Event()

        await _oai_to_browser(
            oai_ws,
            browser_ws,
            questions,
            interview_ended,
            controller,
            decline_llm=FakeLlm("no"),
            intent_llm=FakeLlm("answer"),
        )

        return (
            controller.transcription_count,
            controller.has_pending_transcription(),
            browser_ws.sent_json,
        )

    transcription_count, has_pending, sent_json = asyncio.run(run_case())

    assert transcription_count == 1
    assert has_pending is False
    assert sent_json == []


def test_failed_transcription_completion_clears_pending_timeout_block(
    questions: list[dict[str, str]],
) -> None:
    async def run_case() -> tuple[int, bool, list[dict]]:
        controller = RealtimeInterviewController(questions)
        controller.handle_input_committed()
        browser_ws = FakeBrowserWebSocket([])
        oai_ws = FakeOaiWebSocket(
            [{"type": "conversation.item.input_audio_transcription.failed"}]
        )
        interview_ended = asyncio.Event()

        await _oai_to_browser(
            oai_ws,
            browser_ws,
            questions,
            interview_ended,
            controller,
            decline_llm=None,
        )

        return (
            controller.transcription_count,
            controller.has_pending_transcription(),
            browser_ws.sent_json,
        )

    transcription_count, has_pending, sent_json = asyncio.run(run_case())

    assert transcription_count == 1
    assert has_pending is False
    assert sent_json == [
        {
            "type": "transcription.failed",
            "transcription_count": 1,
            "message": "음성 전사에 실패했습니다. 다시 말씀해 주세요.",
        }
    ]


def test_more_timeout_waits_for_pending_transcription(
    questions: list[dict[str, str]],
) -> None:
    controller = RealtimeInterviewController(questions)
    controller.begin_opening()
    controller.handle_playback_done()
    controller.handle_user_transcript("20201234 홍길동", intent=StudentIntent.ANSWER)
    controller.handle_playback_done()
    controller.handle_user_transcript("본문 답변", intent=StudentIntent.ANSWER)
    controller.handle_playback_done()
    controller.handle_input_committed()

    action = controller.handle_input_timeout("more")

    assert controller.answers == []
    assert controller.state == RealtimeInterviewState.LISTENING_MORE
    assert action.browser_messages == [
        {
            "type": "info",
            "message": "음성 전사가 아직 완료되지 않아 추가 답변 확정을 잠시 보류합니다.",
        }
    ]


def test_playback_done_opens_input_only_after_ack(
    questions: list[dict[str, str]],
) -> None:
    controller = RealtimeInterviewController(questions)

    controller.begin_opening()

    assert controller.input_open is False
    assert controller.awaiting_playback_done is True

    action = controller.handle_playback_done()

    assert controller.input_open is True
    assert controller.state == RealtimeInterviewState.LISTENING_IDENTITY
    assert action.browser_messages == [
        {
            "type": "input.open",
            "mode": "identity",
            "timeout_seconds": 60,
            "message": "답변을 말씀해 주세요",
        }
    ]


def test_browser_page_uses_http_turn_api_instead_of_realtime_websocket() -> None:
    assert "/api/project-evaluations/${EVAL_ID}/sessions/${SESSION_ID}/interview" in _HTML
    assert "`${API_BASE}/state`" in _HTML
    assert "`${API_BASE}/answer`" in _HTML
    assert "`${API_BASE}/complete`" in _HTML
    assert "`${API_BASE}/transcribe`" in _HTML
    assert "current_question_id: currentQuestion.id" in _HTML
    assert "new WebSocket(" not in _HTML
    assert "/ws/interview/" not in _HTML
    assert "getUserMedia" not in _HTML


def test_legacy_realtime_websocket_returns_disabled_message() -> None:
    with TestClient(app).websocket_connect("/ws/interview/evaluation-id/session-id") as websocket:
        message = websocket.receive_json()

    assert message == {
        "type": "error",
        "message": "실시간 WebSocket 인터뷰는 비활성화되었습니다. 단계형 HTTP 인터뷰 페이지를 사용하세요.",
        "interview_url": "/interview/evaluation-id/session-id",
    }


def test_browser_audio_is_dropped_while_input_closed(
    questions: list[dict[str, str]],
) -> None:
    async def run_case() -> tuple[list[dict], bool]:
        controller = RealtimeInterviewController(questions)
        browser_ws = FakeBrowserWebSocket(
            [
                {"bytes": b"closed-audio"},
                {"text": json.dumps({"type": "interview.end"})},
            ]
        )
        oai_ws = FakeOaiWebSocket()
        interview_ended = asyncio.Event()

        await _browser_to_oai(browser_ws, oai_ws, interview_ended, controller)

        return oai_ws.sent, interview_ended.is_set()

    sent, ended = asyncio.run(run_case())

    assert sent == [
        {
            "type": "response.create",
            "response": {
                "modalities": ["audio"],
                "instructions": "아래 종료 멘트만 말하세요. 다른 설명을 추가하지 마세요.\n\n인터뷰를 마치겠습니다. 수고하셨습니다.",
            },
        }
    ]
    assert ended is True


def test_browser_audio_is_forwarded_while_input_open(
    questions: list[dict[str, str]],
) -> None:
    async def run_case() -> tuple[list[dict], bool]:
        controller = RealtimeInterviewController(questions)
        controller.input_open = True
        browser_ws = FakeBrowserWebSocket(
            [
                {"bytes": b"open-audio"},
                {"text": json.dumps({"type": "interview.end"})},
            ]
        )
        oai_ws = FakeOaiWebSocket()
        interview_ended = asyncio.Event()

        await _browser_to_oai(browser_ws, oai_ws, interview_ended, controller)

        return oai_ws.sent, interview_ended.is_set()

    sent, ended = asyncio.run(run_case())

    assert sent[0] == {
        "type": "input_audio_buffer.append",
        "audio": base64.b64encode(b"open-audio").decode(),
    }
    assert sent[-1]["type"] == "response.create"
    assert ended is True


def test_browser_oversized_audio_frame_is_rejected(
    questions: list[dict[str, str]],
) -> None:
    async def run_case() -> tuple[list[dict], bool]:
        controller = RealtimeInterviewController(questions)
        controller.input_open = True
        browser_ws = FakeBrowserWebSocket([{"bytes": b"x" * (64 * 1024 + 1)}])
        oai_ws = FakeOaiWebSocket()
        interview_ended = asyncio.Event()

        await _browser_to_oai(browser_ws, oai_ws, interview_ended, controller)

        return browser_ws.sent_json, interview_ended.is_set()

    sent_json, ended = asyncio.run(run_case())

    assert sent_json == [
        {"type": "error", "message": "브라우저 음성 입력 처리 중 오류가 발생했습니다."}
    ]
    assert ended is True


def test_malformed_browser_control_message_is_reported(
    questions: list[dict[str, str]],
) -> None:
    async def run_case() -> tuple[list[dict], bool]:
        controller = RealtimeInterviewController(questions)
        browser_ws = FakeBrowserWebSocket([{"text": "not-json"}])
        oai_ws = FakeOaiWebSocket()
        interview_ended = asyncio.Event()

        await _browser_to_oai(browser_ws, oai_ws, interview_ended, controller)

        return browser_ws.sent_json, interview_ended.is_set()

    sent_json, ended = asyncio.run(run_case())

    assert sent_json == [
        {
            "type": "error",
            "message": "브라우저 제어 메시지 JSON 파싱 실패: Expecting value",
        }
    ]
    assert ended is True


def test_browser_to_oai_send_failure_is_reported(
    questions: list[dict[str, str]],
) -> None:
    async def run_case() -> tuple[list[dict], bool, bool]:
        controller = RealtimeInterviewController(questions)
        controller.input_open = True
        browser_ws = FakeBrowserWebSocket([{"bytes": b"audio"}])
        oai_ws = FakeOaiWebSocket(fail_send=True)
        interview_ended = asyncio.Event()
        realtime_failed = asyncio.Event()

        await _browser_to_oai(
            browser_ws,
            oai_ws,
            interview_ended,
            controller,
            realtime_failed=realtime_failed,
        )

        return browser_ws.sent_json, interview_ended.is_set(), realtime_failed.is_set()

    sent_json, ended, failed = asyncio.run(run_case())

    assert sent_json == [
        {"type": "error", "message": "브라우저 음성 입력 처리 중 오류가 발생했습니다."}
    ]
    assert ended is True
    assert failed is True


def test_oai_error_event_is_reported_and_terminates(
    questions: list[dict[str, str]],
) -> None:
    async def run_case() -> tuple[list[dict], bool, bool]:
        controller = RealtimeInterviewController(questions)
        browser_ws = FakeBrowserWebSocket([])
        interview_ended = asyncio.Event()
        realtime_failed = asyncio.Event()
        oai_ws = FakeOaiWebSocket(
            [
                {
                    "type": "error",
                    "error": {
                        "message": "Realtime failed",
                        "code": "bad_request",
                        "param": "response.modalities",
                    },
                }
            ]
        )
        await _oai_to_browser(
            oai_ws,
            browser_ws,
            questions,
            interview_ended,
            controller,
            decline_llm=None,
            realtime_failed=realtime_failed,
        )
        return browser_ws.sent_json, interview_ended.is_set(), realtime_failed.is_set()

    sent_json, ended, failed = asyncio.run(run_case())

    assert sent_json == [
        {
            "type": "error",
            "message": "OpenAI Realtime 오류: Realtime failed / param=response.modalities / code=bad_request",
        }
    ]
    assert ended is True
    assert failed is True


def test_oai_event_processing_error_marks_realtime_failed(
    questions: list[dict[str, str]],
) -> None:
    async def run_case() -> tuple[list[dict], bool, bool]:
        controller = RealtimeInterviewController(questions)
        browser_ws = FakeBrowserWebSocket([])
        interview_ended = asyncio.Event()
        realtime_failed = asyncio.Event()
        await _oai_to_browser(
            FakeOaiWebSocket(["not-json"]),
            browser_ws,
            questions,
            interview_ended,
            controller,
            decline_llm=None,
            realtime_failed=realtime_failed,
        )
        return browser_ws.sent_json, interview_ended.is_set(), realtime_failed.is_set()

    sent_json, ended, failed = asyncio.run(run_case())

    assert sent_json == [
        {
            "type": "error",
            "message": "Realtime 서버 이벤트 처리 중 오류가 발생했습니다.",
        }
    ]
    assert ended is True
    assert failed is True


def test_server_more_timeout_failure_marks_realtime_failed(
    questions: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run_case() -> tuple[list[dict], bool, bool]:
        controller = RealtimeInterviewController(questions)
        controller.begin_opening()
        controller.handle_playback_done()
        controller.handle_user_transcript(
            "20201234 홍길동", intent=StudentIntent.ANSWER
        )
        controller.handle_playback_done()
        controller.handle_user_transcript("본문 답변", intent=StudentIntent.ANSWER)
        controller.handle_playback_done()
        browser_ws = FakeBrowserWebSocket([])
        oai_ws = FakeOaiWebSocket(fail_send=True)
        interview_ended = asyncio.Event()
        realtime_failed = asyncio.Event()
        transition_lock = asyncio.Lock()
        timeouts = RealtimeServerTimeouts(transition_lock, realtime_failed)

        async def immediate_sleep(_seconds: int) -> None:
            return None

        monkeypatch.setattr(asyncio, "sleep", immediate_sleep)
        timeouts.sync_with_controller(controller, browser_ws, oai_ws, interview_ended)
        task = timeouts.more_timeout_task
        assert task is not None
        await task

        return browser_ws.sent_json, interview_ended.is_set(), realtime_failed.is_set()

    sent_json, ended, failed = asyncio.run(run_case())

    assert sent_json[-1] == {
        "type": "error",
        "message": "추가 답변 timeout 처리 중 오류가 발생했습니다.",
    }
    assert ended is True
    assert failed is True


def test_server_more_timeout_completes_answer_without_browser_timeout(
    questions: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run_case() -> tuple[list[str], RealtimeInterviewState, list[dict]]:
        controller = RealtimeInterviewController(questions)
        browser_ws = FakeBrowserWebSocket([])
        oai_ws = FakeOaiWebSocket()
        interview_ended = asyncio.Event()
        transition_lock = asyncio.Lock()
        timeouts = RealtimeServerTimeouts(transition_lock)

        controller.begin_opening()
        controller.handle_playback_done()
        controller.handle_user_transcript(
            "20201234 홍길동", intent=StudentIntent.ANSWER
        )
        controller.handle_playback_done()
        controller.handle_user_transcript("본문 답변", intent=StudentIntent.ANSWER)
        controller.handle_playback_done()

        async def immediate_sleep(_seconds: int) -> None:
            return None

        monkeypatch.setattr(asyncio, "sleep", immediate_sleep)
        timeouts.sync_with_controller(controller, browser_ws, oai_ws, interview_ended)
        task = timeouts.more_timeout_task
        assert task is not None
        await task

        return controller.answers, controller.state, oai_ws.sent

    answers, state, sent = asyncio.run(run_case())

    assert answers == ["본문 답변"]
    assert state == RealtimeInterviewState.ASKING_QUESTION
    assert sent[-1]["type"] == "response.create"


def test_more_transcript_cancels_server_timeout_during_decline_classification(
    questions: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run_case() -> tuple[list[str], RealtimeInterviewState, list[dict]]:
        controller = RealtimeInterviewController(questions)
        controller.begin_opening()
        controller.handle_playback_done()
        controller.handle_user_transcript(
            "20201234 홍길동", intent=StudentIntent.ANSWER
        )
        controller.handle_playback_done()
        controller.handle_user_transcript("본문 답변", intent=StudentIntent.ANSWER)
        controller.handle_playback_done()
        browser_ws = FakeBrowserWebSocket([])
        oai_ws = FakeOaiWebSocket(
            [
                {
                    "type": "conversation.item.input_audio_transcription.completed",
                    "transcript": "추가 답변",
                }
            ]
        )
        interview_ended = asyncio.Event()
        transition_lock = asyncio.Lock()
        timeouts = RealtimeServerTimeouts(transition_lock)

        async def delayed_sleep(_seconds: int) -> None:
            await original_sleep(0.001)

        original_sleep = asyncio.sleep
        monkeypatch.setattr(asyncio, "sleep", delayed_sleep)
        timeouts.sync_with_controller(controller, browser_ws, oai_ws, interview_ended)
        await _oai_to_browser(
            oai_ws,
            browser_ws,
            questions,
            interview_ended,
            controller,
            decline_llm=FakeLlm("no", delay=0.01),
            intent_llm=FakeLlm("answer"),
            transition_lock=transition_lock,
            timeouts=timeouts,
        )

        return controller.answers, controller.state, oai_ws.sent

    answers, state, sent = asyncio.run(run_case())

    assert answers == []
    assert state == RealtimeInterviewState.ASKING_MORE
    assert sent[-1]["type"] == "response.create"


def test_more_timeout_is_cancelled_while_user_is_speaking(
    questions: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run_case() -> tuple[list[str], list[dict], bool]:
        controller = RealtimeInterviewController(questions)
        controller.begin_opening()
        controller.handle_playback_done()
        controller.handle_user_transcript(
            "20201234 홍길동", intent=StudentIntent.ANSWER
        )
        controller.handle_playback_done()
        controller.handle_user_transcript("본문 답변", intent=StudentIntent.ANSWER)
        controller.handle_playback_done()
        browser_ws = FakeBrowserWebSocket([])
        oai_ws = FakeOaiWebSocket([{"type": "input_audio_buffer.speech_started"}])
        interview_ended = asyncio.Event()
        transition_lock = asyncio.Lock()
        timeouts = RealtimeServerTimeouts(transition_lock)

        async def immediate_sleep(_seconds: int) -> None:
            return None

        monkeypatch.setattr(asyncio, "sleep", immediate_sleep)
        timeouts.sync_with_controller(controller, browser_ws, oai_ws, interview_ended)
        await _oai_to_browser(
            oai_ws,
            browser_ws,
            questions,
            interview_ended,
            controller,
            decline_llm=FakeLlm("no"),
            intent_llm=FakeLlm("answer"),
            transition_lock=transition_lock,
            timeouts=timeouts,
        )

        return (
            controller.answers,
            browser_ws.sent_json,
            bool(timeouts.more_timeout_task),
        )

    answers, sent_json, has_timeout = asyncio.run(run_case())

    assert answers == []
    assert sent_json == [{"type": "vad.speech_started"}]
    assert has_timeout is False


def test_more_timeout_rearms_after_speech_stopped(
    questions: list[dict[str, str]],
) -> None:
    async def run_case() -> tuple[bool, list[dict]]:
        controller = RealtimeInterviewController(questions)
        controller.begin_opening()
        controller.handle_playback_done()
        controller.handle_user_transcript(
            "20201234 홍길동", intent=StudentIntent.ANSWER
        )
        controller.handle_playback_done()
        controller.handle_user_transcript("본문 답변", intent=StudentIntent.ANSWER)
        controller.handle_playback_done()
        browser_ws = FakeBrowserWebSocket([])
        oai_ws = FakeOaiWebSocket(
            [
                {"type": "input_audio_buffer.speech_started"},
                {"type": "input_audio_buffer.speech_stopped"},
            ]
        )
        interview_ended = asyncio.Event()
        transition_lock = asyncio.Lock()
        timeouts = RealtimeServerTimeouts(transition_lock)

        timeouts.sync_with_controller(controller, browser_ws, oai_ws, interview_ended)
        await _oai_to_browser(
            oai_ws,
            browser_ws,
            questions,
            interview_ended,
            controller,
            decline_llm=FakeLlm("no"),
            intent_llm=FakeLlm("answer"),
            transition_lock=transition_lock,
            timeouts=timeouts,
        )
        rearmed = timeouts.more_timeout_task is not None
        timeouts.cancel_more_timeout()

        return rearmed, browser_ws.sent_json

    rearmed, sent_json = asyncio.run(run_case())

    assert rearmed is True
    assert sent_json[:2] == [
        {"type": "vad.speech_started"},
        {"type": "vad.speech_stopped"},
    ]
