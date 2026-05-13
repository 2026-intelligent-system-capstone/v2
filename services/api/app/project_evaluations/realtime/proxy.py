"""OpenAI Realtime WebSocket proxy.

이 모듈은 transport 어댑터다.
- Realtime API: TTS/STT/VAD 음성 입출력에만 사용한다.
- 평가 결정(질문 진행, follow-up, 종료, 리포트)은 `InterviewTurnFlow.submit_answer`와
  `ProjectEvaluationService.complete_session`이 단독 권한자다.

proxy 내부에는 질문 인덱스, 답변 목록, final report 캐시 등 평가 상태가 없다.
transcript가 들어오면 현재 input 모드(`identity`, `answer`, `more`, `follow_up`)에 맞는
`InterviewTurnFlowRequest`로 변환해 core에 위임하고, 응답으로 받은 다음 TTS 멘트만
브라우저/OpenAI에 흘려보낸다.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

from services.api.app.project_evaluations.domain.models import (
    EvaluationReportRead,
    InterviewQuestionRead,
    InterviewTurnFlowRequest,
    InterviewTurnFlowResponse,
    InterviewTurnFlowStatus,
    InterviewTurnMode,
)
from services.api.app.project_evaluations.interview.turn_flow import InterviewTurnFlow
from services.api.app.project_evaluations.persistence.repository import (
    ProjectEvaluationRepository,
)
from services.api.app.project_evaluations.realtime.controller import (
    RealtimeControllerAction,
    RealtimeUxController,
    VoiceInputMode,
)
from services.api.app.project_evaluations.service import ProjectEvaluationService

_REALTIME_WS_BASE = "wss://api.openai.com/v1/realtime"
MAX_BROWSER_AUDIO_FRAME_BYTES = 64 * 1024
DEFAULT_MODEL = "gpt-realtime-2"
DEFAULT_TRANSCRIBE_MODEL = "gpt-4o-transcribe"
DEFAULT_LANGUAGE = "ko"
DEFAULT_MORE_TIMEOUT_SECONDS = 15
DEFAULT_MORE_PROMPT = "추가로 말씀하실 내용이 있으실까요?"

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _SessionContext:
    """transport 변환에 필요한 최소 컨텍스트.

    질문 인덱스/답변/리포트의 권위는 turn_flow/service에 있고, 여기서는 다음
    `InterviewTurnFlowRequest`를 만들기 위한 직전 응답만 보관한다.
    """

    current_question_id: str | None = None
    draft_answer: str = ""
    follow_up_question: str = ""
    follow_up_reason: str = ""


@dataclass(slots=True)
class RealtimeServerTimeouts:
    transition_lock: asyncio.Lock
    realtime_failed: asyncio.Event | None = None
    more_timeout_task: asyncio.Task[None] | None = None

    def cancel_more_timeout(self) -> None:
        task = self.more_timeout_task
        self.more_timeout_task = None
        if task is not None:
            task.cancel()


async def run_realtime_session(
    browser_ws: WebSocket,
    session_factory: Callable[[], Any],
    settings: Any,
    evaluation_id: str,
    session_id: str,
    session_token: str,
    client_id: str,
    model: str = DEFAULT_MODEL,
) -> None:
    await browser_ws.accept()

    if not settings.OPENAI_API_KEY:
        await browser_ws.send_json(
            {"type": "error", "message": "OPENAI_API_KEY가 설정되지 않았습니다."}
        )
        await browser_ws.close()
        return

    def submit_answer(payload: InterviewTurnFlowRequest) -> InterviewTurnFlowResponse:
        with session_factory() as db_session:
            service = ProjectEvaluationService(
                ProjectEvaluationRepository(db_session),
                settings,
            )
            return InterviewTurnFlow(service).submit_answer(
                evaluation_id,
                session_id,
                payload,
                session_token,
                client_id,
            )

    def complete_interview() -> EvaluationReportRead:
        with session_factory() as db_session:
            service = ProjectEvaluationService(
                ProjectEvaluationRepository(db_session),
                settings,
            )
            return service.complete_session(
                evaluation_id,
                session_id,
                session_token,
                client_id,
            )

    def get_first_question() -> InterviewQuestionRead | None:
        with session_factory() as db_session:
            service = ProjectEvaluationService(
                ProjectEvaluationRepository(db_session),
                settings,
            )
            session = service.ensure_session(
                evaluation_id, session_id, session_token, client_id
            )
            questions = service.repository.list_question_rows(evaluation_id)
            if session.current_question_index >= len(questions):
                return None
            return service.repository.to_question_read(
                questions[session.current_question_index]
            )

    context = _SessionContext()
    controller = RealtimeUxController()
    interview_ended = asyncio.Event()
    realtime_failed = asyncio.Event()
    transition_lock = asyncio.Lock()
    timeouts = RealtimeServerTimeouts(transition_lock, realtime_failed)

    oai_ws_headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1",
    }

    try:
        async with websockets.connect(
            f"{_REALTIME_WS_BASE}?model={model}",
            additional_headers=oai_ws_headers,
            compression=None,
        ) as oai_ws:
            await _configure_session(
                oai_ws,
                _transport_instructions(),
                model=model,
            )
            opening_action = controller.queue_opening()
            await _apply_controller_action(browser_ws, oai_ws, opening_action)

            t_b2o = asyncio.create_task(
                _browser_to_oai(
                    browser_ws,
                    oai_ws,
                    interview_ended,
                    controller,
                    context,
                    submit_answer=submit_answer,
                    complete_interview=complete_interview,
                    realtime_failed=realtime_failed,
                    transition_lock=transition_lock,
                    timeouts=timeouts,
                )
            )
            t_o2b = asyncio.create_task(
                _oai_to_browser(
                    oai_ws,
                    browser_ws,
                    interview_ended,
                    controller,
                    context,
                    submit_answer=submit_answer,
                    complete_interview=complete_interview,
                    get_first_question=get_first_question,
                    realtime_failed=realtime_failed,
                    transition_lock=transition_lock,
                    timeouts=timeouts,
                )
            )

            await interview_ended.wait()
            timeouts.cancel_more_timeout()
            t_b2o.cancel()
            t_o2b.cancel()
            await asyncio.gather(t_b2o, t_o2b, return_exceptions=True)
    except Exception as exc:
        logger.error("Realtime proxy error: %s", exc)
        try:
            await browser_ws.send_json(
                {"type": "error", "message": f"Realtime 연결 오류: {exc}"}
            )
        except Exception:
            pass
    finally:
        try:
            await browser_ws.close()
        except Exception:
            pass


def _transport_instructions() -> str:
    return (
        "당신은 실시간 프로젝트 평가 음성 인터페이스입니다. "
        "반드시 response.create로 전달된 문장만 한국어로 자연스럽게 읽고, "
        "자체적으로 질문을 만들거나 대화를 이어가지 마세요."
    )


def _session_update_payload(instructions: str, model: str) -> dict[str, object]:
    return {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "instructions": instructions,
            "voice": "coral",
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_transcription": {
                "model": "whisper-1",
                "language": DEFAULT_LANGUAGE,
            },
            "turn_detection": None,
        },
    }


async def _configure_session(
    oai_ws: Any,
    instructions: str,
    *,
    model: str = DEFAULT_MODEL,
    session_update_timeout: float = 5.0,
) -> None:
    await oai_ws.send(json.dumps(_session_update_payload(instructions, model)))

    while True:
        try:
            raw_msg = await asyncio.wait_for(oai_ws.recv(), timeout=session_update_timeout)
        except TimeoutError as exc:
            raise RuntimeError("OpenAI Realtime session.updated 응답을 받지 못했습니다.") from exc
        except ConnectionClosed as exc:
            raise RuntimeError("OpenAI Realtime session.updated 응답을 받지 못했습니다.") from exc
        event = json.loads(raw_msg)
        event_type = str(event.get("type") or "")
        if event_type == "session.updated":
            return
        if event_type == "error":
            raise RuntimeError(_format_openai_error(event.get("error", {})))


async def _create_audio_response(oai_ws: Any, instructions: str) -> None:
    """CLI realtime_client와 동일한 GA wire 패턴.

    instructions만 response.create에 넘기면 GA 모델은 입력 user 메시지가 없어
    응답 audio를 생성하지 않을 수 있다. CLI처럼 conversation에 user input_text를
    먼저 넣은 뒤 빈 response.create로 모델이 그 메시지를 자연스럽게 읽게 한다.
    """
    await oai_ws.send(
        json.dumps(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"다음 내용을 자연스럽게 읽어주세요:\n\n{instructions}",
                        }
                    ],
                },
            }
        )
    )
    await oai_ws.send(
        json.dumps(
            {
                "type": "response.create",
                "response": {"modalities": ["audio", "text"]},
            }
        )
    )


async def _apply_controller_action(
    browser_ws: WebSocket,
    oai_ws: Any,
    action: RealtimeControllerAction,
) -> None:
    has_input_open = any(m.get("type") == "input.open" for m in action.browser_messages)
    if has_input_open:
        await oai_ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
    for message in action.browser_messages:
        await browser_ws.send_json(message)
    if action.prompt_text:
        await oai_ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
        await browser_ws.send_json({"type": "prompt.queued", "text": action.prompt_text})
        await _create_audio_response(oai_ws, action.prompt_text)


def _sync_more_timeout(
    controller: RealtimeUxController,
    browser_ws: WebSocket,
    oai_ws: Any,
    interview_ended: asyncio.Event,
    timeouts: RealtimeServerTimeouts,
    submit_answer: Callable[[InterviewTurnFlowRequest], InterviewTurnFlowResponse],
    complete_interview: Callable[[], EvaluationReportRead],
    context: _SessionContext,
) -> None:
    """controller가 'more' 입력을 기다리는 상태에서만 서버측 timeout을 걸어둔다."""

    timeouts.cancel_more_timeout()
    if interview_ended.is_set():
        return
    if controller.pending_input_mode != VoiceInputMode.MORE or not controller.input_open:
        return
    timeouts.more_timeout_task = asyncio.create_task(
        _run_more_timeout(
            controller,
            browser_ws,
            oai_ws,
            interview_ended,
            timeouts,
            submit_answer,
            complete_interview,
            context,
        )
    )


async def _run_more_timeout(
    controller: RealtimeUxController,
    browser_ws: WebSocket,
    oai_ws: Any,
    interview_ended: asyncio.Event,
    timeouts: RealtimeServerTimeouts,
    submit_answer: Callable[[InterviewTurnFlowRequest], InterviewTurnFlowResponse],
    complete_interview: Callable[[], EvaluationReportRead],
    context: _SessionContext,
) -> None:
    try:
        await asyncio.sleep(DEFAULT_MORE_TIMEOUT_SECONDS)
        async with timeouts.transition_lock:
            if interview_ended.is_set():
                return
            if controller.has_pending_transcription():
                await browser_ws.send_json(
                    {
                        "type": "info",
                        "message": "음성 전사가 아직 완료되지 않아 추가 답변 확정을 잠시 보류합니다.",
                    }
                )
                return
            response = await asyncio.to_thread(
                submit_answer,
                _flow_request(
                    context,
                    mode=InterviewTurnMode.MORE,
                    answer_text="없습니다.",
                ),
            )
            action = await _apply_flow_response(
                response,
                context,
                controller,
            )
            await _apply_controller_action(browser_ws, oai_ws, action)
            _sync_more_timeout(
                controller,
                browser_ws,
                oai_ws,
                interview_ended,
                timeouts,
                submit_answer,
                complete_interview,
                context,
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        if timeouts.realtime_failed is not None:
            timeouts.realtime_failed.set()
        interview_ended.set()
        await browser_ws.send_json(
            {
                "type": "error",
                "message": "추가 답변 timeout 처리 중 오류가 발생했습니다.",
            }
        )


def _flow_request(
    context: _SessionContext,
    *,
    mode: InterviewTurnMode,
    answer_text: str,
) -> InterviewTurnFlowRequest:
    return InterviewTurnFlowRequest(
        mode=mode,
        answer_text=answer_text,
        draft_answer=context.draft_answer,
        follow_up_question=context.follow_up_question,
        follow_up_reason=context.follow_up_reason,
        current_question_id=context.current_question_id,
    )


async def _apply_flow_response(
    response: InterviewTurnFlowResponse,
    context: _SessionContext,
    controller: RealtimeUxController,
) -> RealtimeControllerAction:
    """turn_flow 응답 → controller TTS prompt + 다음 input 모드.

    여기서는 어떤 평가 결정도 하지 않는다. core 응답을 transport 표현으로 옮기기만 한다.
    """

    context.draft_answer = (response.draft_answer or "").strip()
    context.follow_up_question = (response.follow_up_question or "").strip()
    context.follow_up_reason = (response.follow_up_reason or "").strip()

    if response.status == InterviewTurnFlowStatus.NEED_MORE:
        action = controller.queue_prompt(DEFAULT_MORE_PROMPT, VoiceInputMode.MORE)
        if response.message:
            action.browser_messages.insert(
                0, {"type": "info", "message": response.message}
            )
        return action

    if response.status == InterviewTurnFlowStatus.NEED_FOLLOW_UP:
        follow_up_text = context.follow_up_question or "조금 더 구체적으로 설명해 주세요."
        action = controller.queue_prompt(follow_up_text, VoiceInputMode.FOLLOW_UP)
        if response.message:
            action.browser_messages.insert(
                0, {"type": "info", "message": response.message}
            )
        return action

    context.draft_answer = ""
    context.follow_up_question = ""
    context.follow_up_reason = ""

    if response.status == InterviewTurnFlowStatus.TURN_SUBMITTED:
        next_question = response.next_question
        if next_question is not None:
            context.current_question_id = next_question.id
            action = controller.queue_prompt(next_question.question, VoiceInputMode.ANSWER)
        else:
            action = controller.queue_closing()
        if response.message:
            action.browser_messages.insert(
                0, {"type": "info", "message": response.message}
            )
        return action

    if response.status in {
        InterviewTurnFlowStatus.READY_TO_COMPLETE,
        InterviewTurnFlowStatus.COMPLETED,
    }:
        context.current_question_id = None
        action = controller.queue_closing()
        if response.message:
            action.browser_messages.insert(
                0, {"type": "info", "message": response.message}
            )
        return action

    return RealtimeControllerAction()


async def _browser_to_oai(
    browser_ws: WebSocket,
    oai_ws: Any,
    interview_ended: asyncio.Event,
    controller: RealtimeUxController,
    context: _SessionContext,
    *,
    submit_answer: Callable[[InterviewTurnFlowRequest], InterviewTurnFlowResponse] | None = None,
    complete_interview: Callable[[], EvaluationReportRead] | None = None,
    realtime_failed: asyncio.Event | None = None,
    transition_lock: asyncio.Lock | None = None,
    timeouts: RealtimeServerTimeouts | None = None,
) -> None:
    try:
        while not interview_ended.is_set():
            msg = await browser_ws.receive()
            if msg.get("type") == "websocket.disconnect":
                interview_ended.set()
                break
            if msg.get("bytes") is not None:
                audio = msg["bytes"]
                if len(audio) > MAX_BROWSER_AUDIO_FRAME_BYTES:
                    raise RuntimeError("browser_audio_frame_too_large")
                if not controller.input_open:
                    continue
                await oai_ws.send(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(audio).decode(),
                        }
                    )
                )
                continue
            if msg.get("text") is None:
                continue
            try:
                data = json.loads(msg["text"])
            except json.JSONDecodeError as exc:
                await browser_ws.send_json(
                    {
                        "type": "error",
                        "message": f"브라우저 제어 메시지 JSON 파싱 실패: {exc.msg}",
                    }
                )
                if realtime_failed is not None:
                    realtime_failed.set()
                interview_ended.set()
                return
            msg_type = data.get("type")
            if msg_type == "ptt.commit":
                await oai_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                continue
            if msg_type != "interview.end":
                continue
            if transition_lock is None:
                transition_lock = asyncio.Lock()
            async with transition_lock:
                if controller.has_pending_transcription():
                    await browser_ws.send_json(
                        {
                            "type": "info",
                            "message": "마지막 답변을 처리 중입니다. 잠시만 기다려 주세요.",
                        }
                    )
                    continue
                if submit_answer is None or complete_interview is None:
                    action = controller.queue_closing()
                else:
                    response = await asyncio.to_thread(
                        submit_answer,
                        _flow_request(
                            context,
                            mode=InterviewTurnMode.END,
                            answer_text=" ",
                        ),
                    )
                    action = await _apply_flow_response(response, context, controller)
                await _apply_controller_action(browser_ws, oai_ws, action)
                if (
                    timeouts is not None
                    and submit_answer is not None
                    and complete_interview is not None
                ):
                    _sync_more_timeout(
                        controller,
                        browser_ws,
                        oai_ws,
                        interview_ended,
                        timeouts,
                        submit_answer,
                        complete_interview,
                        context,
                    )
    except WebSocketDisconnect:
        interview_ended.set()
    except asyncio.CancelledError:
        raise
    except Exception:
        await browser_ws.send_json(
            {"type": "error", "message": "브라우저 음성 입력 처리 중 오류가 발생했습니다."}
        )
        if realtime_failed is not None:
            realtime_failed.set()
        interview_ended.set()


async def _oai_to_browser(
    oai_ws: Any,
    browser_ws: WebSocket,
    interview_ended: asyncio.Event,
    controller: RealtimeUxController,
    context: _SessionContext,
    *,
    submit_answer: Callable[[InterviewTurnFlowRequest], InterviewTurnFlowResponse] | None = None,
    complete_interview: Callable[[], EvaluationReportRead] | None = None,
    get_first_question: Callable[[], InterviewQuestionRead | None] | None = None,
    realtime_failed: asyncio.Event | None = None,
    transition_lock: asyncio.Lock | None = None,
    timeouts: RealtimeServerTimeouts | None = None,
) -> None:
    transition_lock = transition_lock or asyncio.Lock()
    try:
        while not interview_ended.is_set():
            raw_msg = await oai_ws.recv()
            event = json.loads(raw_msg)
            event_type = str(event.get("type") or "")

            if event_type in ("response.audio.delta", "response.output_audio.delta"):
                delta = event.get("delta", "")
                if delta:
                    await browser_ws.send_bytes(base64.b64decode(delta))
                continue

            if event_type in ("response.audio.done", "response.output_audio.done"):
                # 브라우저 측 UI 호환을 위해 메시지 이름은 `response.audio.done` 유지.
                await browser_ws.send_json({"type": "response.audio.done"})
                async with transition_lock:
                    was_closing = controller.closing
                    action = controller.handle_playback_done()
                    await _apply_controller_action(browser_ws, oai_ws, action)
                    if was_closing and complete_interview is not None:
                        try:
                            report = await asyncio.to_thread(complete_interview)
                            await browser_ws.send_json(
                                {
                                    "type": "interview.complete",
                                    "report": _report_payload(report),
                                }
                            )
                        except Exception as exc:
                            logger.error("complete_interview failed: %s", exc, exc_info=True)
                            await browser_ws.send_json(
                                {
                                    "type": "error",
                                    "message": "리포트 생성 중 오류가 발생했습니다. 단계형 화면에서 리포트를 확인하세요.",
                                }
                            )
                        interview_ended.set()
                        return
                    if (
                        timeouts is not None
                        and submit_answer is not None
                        and complete_interview is not None
                    ):
                        _sync_more_timeout(
                            controller,
                            browser_ws,
                            oai_ws,
                            interview_ended,
                            timeouts,
                            submit_answer,
                            complete_interview,
                            context,
                        )
                continue

            if event_type == "response.done":
                await browser_ws.send_json({"type": "response.done"})
                continue

            if event_type == "input_audio_buffer.committed":
                controller.handle_input_committed()
                continue

            if event_type == "input_audio_buffer.speech_started":
                if timeouts is not None:
                    timeouts.cancel_more_timeout()
                await browser_ws.send_json({"type": "vad.speech_started"})
                continue

            if event_type == "input_audio_buffer.speech_stopped":
                await browser_ws.send_json({"type": "vad.speech_stopped"})
                if (
                    timeouts is not None
                    and submit_answer is not None
                    and complete_interview is not None
                ):
                    _sync_more_timeout(
                        controller,
                        browser_ws,
                        oai_ws,
                        interview_ended,
                        timeouts,
                        submit_answer,
                        complete_interview,
                        context,
                    )
                continue

            if event_type == "conversation.item.input_audio_transcription.failed":
                async with transition_lock:
                    action = controller.handle_transcription_failed()
                    await _apply_controller_action(browser_ws, oai_ws, action)
                    if (
                        timeouts is not None
                        and submit_answer is not None
                        and complete_interview is not None
                    ):
                        _sync_more_timeout(
                            controller,
                            browser_ws,
                            oai_ws,
                            interview_ended,
                            timeouts,
                            submit_answer,
                            complete_interview,
                            context,
                        )
                continue

            if event_type != "conversation.item.input_audio_transcription.completed":
                if event_type == "error":
                    await browser_ws.send_json(
                        {
                            "type": "error",
                            "message": _format_openai_error(event.get("error", {})),
                        }
                    )
                    if realtime_failed is not None:
                        realtime_failed.set()
                    interview_ended.set()
                    return
                continue

            controller.handle_transcription_completed()
            transcript = str(event.get("transcript") or "").strip()
            if not transcript:
                if (
                    timeouts is not None
                    and submit_answer is not None
                    and complete_interview is not None
                ):
                    _sync_more_timeout(
                        controller,
                        browser_ws,
                        oai_ws,
                        interview_ended,
                        timeouts,
                        submit_answer,
                        complete_interview,
                        context,
                    )
                continue

            async with transition_lock:
                mode = controller.pending_input_mode
                controller.close_input()
                if mode is None or controller.closing:
                    continue

                if mode == VoiceInputMode.IDENTITY:
                    await browser_ws.send_json(
                        {
                            "type": "transcript.user",
                            "text": transcript,
                            "is_identity_answer": True,
                        }
                    )
                    if get_first_question is None:
                        action = controller.queue_closing()
                    else:
                        first_question = await asyncio.to_thread(get_first_question)
                        if first_question is None:
                            action = controller.queue_closing()
                        else:
                            context.current_question_id = first_question.id
                            action = controller.queue_prompt(
                                first_question.question, VoiceInputMode.ANSWER
                            )
                    await _apply_controller_action(browser_ws, oai_ws, action)
                    continue

                await browser_ws.send_json(
                    {
                        "type": "transcript.user",
                        "text": transcript,
                        "is_identity_answer": False,
                    }
                )

                if submit_answer is None or complete_interview is None:
                    continue

                turn_mode = _voice_mode_to_turn_mode(mode)
                response = await asyncio.to_thread(
                    submit_answer,
                    _flow_request(context, mode=turn_mode, answer_text=transcript),
                )
                action = await _apply_flow_response(response, context, controller)
                await _apply_controller_action(browser_ws, oai_ws, action)
                if timeouts is not None:
                    _sync_more_timeout(
                        controller,
                        browser_ws,
                        oai_ws,
                        interview_ended,
                        timeouts,
                        submit_answer,
                        complete_interview,
                        context,
                    )
    except asyncio.CancelledError:
        raise
    except ConnectionClosed:
        interview_ended.set()
    except Exception:
        await browser_ws.send_json(
            {
                "type": "error",
                "message": "Realtime 서버 이벤트 처리 중 오류가 발생했습니다.",
            }
        )
        if realtime_failed is not None:
            realtime_failed.set()
        interview_ended.set()


def _voice_mode_to_turn_mode(mode: VoiceInputMode) -> InterviewTurnMode:
    if mode == VoiceInputMode.ANSWER:
        return InterviewTurnMode.ANSWER
    if mode == VoiceInputMode.MORE:
        return InterviewTurnMode.MORE
    if mode == VoiceInputMode.FOLLOW_UP:
        return InterviewTurnMode.FOLLOW_UP
    return InterviewTurnMode.ANSWER


def _report_payload(report: Any) -> dict[str, object] | None:
    if report is None:
        return None
    if hasattr(report, "model_dump"):
        return report.model_dump(mode="json")
    if isinstance(report, dict):
        return report
    raise TypeError(f"지원하지 않는 report payload 타입입니다: {type(report)!r}")


def _format_openai_error(error: dict[str, object]) -> str:
    message = str(error.get("message") or "오류 발생")
    parts = [f"OpenAI Realtime 오류: {message}"]
    if error.get("param"):
        parts.append(f"param={error['param']}")
    if error.get("code"):
        parts.append(f"code={error['code']}")
    return " / ".join(parts)
