"""OpenAI Realtime API WebSocket proxy for voice interview."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Awaitable, Callable

import websockets
from fastapi import WebSocket, WebSocketDisconnect

_REALTIME_WS_BASE = "wss://api.openai.com/v1/realtime"

logger = logging.getLogger(__name__)

OPENING_QUESTION = (
    "안녕하세요, 지금부터 프로젝트 평가를 진행하겠습니다. 프로젝트 평가란, "
    "학생분께서 제출한 자료를 바탕으로 이 프로젝트를 실제로 본인이 했는지, "
    "했다면 어느정도 수준까지 이해하고 있는지 확인하는 과정입니다. "
    "우선, 본인의 학번과 이름을 말씀해주세요."
)


def build_interview_instructions(questions: list[dict]) -> str:
    q_lines = "\n".join(
        f"{i + 1}. {q['question']}\n   (의도: {q.get('intent', '')})"
        for i, q in enumerate(questions)
    )
    return f"""당신은 교수의 프로젝트 과제 수행 진위 검증 인터뷰어입니다.
학생/프로젝트 수행자가 제출한 프로젝트를 실제로 수행했고 전체 구조를 이해하는지 확인하는 것이 목적입니다.

[고정 오프닝 질문]
{OPENING_QUESTION}

[프로젝트 검증 질문 목록 — 총 {len(questions)}개]
{q_lines}

[진행 규칙]
- 첫 발화는 반드시 [고정 오프닝 질문]의 문장을 글자 그대로 말하세요.
- 학생이 학번과 이름을 말하면, 그 답변은 평가 답변이 아니라 본인 확인 답변으로만 취급하고 프로젝트 검증 질문 1번으로 넘어가세요.
- 이후 질문은 [프로젝트 검증 질문 목록]의 번호 순서대로 하나씩 그대로 물어보세요.
- 목록에 없는 질문을 새로 만들거나 일반 인터뷰 질문을 추가하지 마세요.
- 회사 지원 동기, 직무 적합성, 입사 이유, 커리어 적합성은 절대 묻지 마세요.
- 특정 함수의 정확한 인자, 반환값, 라인, 분기 조건을 외워야 답할 수 있는 세부 코드 암기 질문은 하지 마세요.
- 각 프로젝트 검증 답변을 듣고, 답변이 너무 짧거나 모호하면 전체 흐름, 설계 이유, 구현 선택, 문제 해결 경험, 한계 인식을 더 설명하게 하는 짧은 꼬리질문을 하나 해도 됩니다.
- 모든 프로젝트 검증 질문이 끝나면 반드시 "인터뷰를 마치겠습니다. 수고하셨습니다."라고 말하고 종료하세요.
- 한국어로만 진행하세요.
- 자기소개나 다른 인사말 없이 고정 오프닝 질문으로 시작하세요."""


async def run_realtime_session(
    browser_ws: WebSocket,
    api_key: str,
    questions: list[dict],
    on_complete: Callable[[list[str]], Awaitable[dict]],
    model: str = "gpt-4o-realtime-preview-2024-12-17",
) -> None:
    """Proxy audio between browser and OpenAI Realtime API for voice interview.

    Collects user transcripts and calls on_complete when interview ends.
    """
    await browser_ws.accept()

    if not api_key:
        await browser_ws.send_json(
            {"type": "error", "message": "OPENAI_API_KEY가 설정되지 않았습니다."}
        )
        await browser_ws.close()
        return

    instructions = build_interview_instructions(questions)
    user_transcripts: list[str] = []
    interview_ended = asyncio.Event()

    oai_ws_headers = {
        "Authorization": f"Bearer {api_key}",
        "OpenAI-Beta": "realtime=v1",
    }

    try:
        async with websockets.connect(
            f"{_REALTIME_WS_BASE}?model={model}",
            additional_headers=oai_ws_headers,
            compression=None,
        ) as oai_ws:
            await _configure_session(oai_ws, instructions)

            t_b2o = asyncio.create_task(
                _browser_to_oai(browser_ws, oai_ws, interview_ended)
            )
            t_o2b = asyncio.create_task(
                _oai_to_browser(
                    oai_ws, browser_ws, user_transcripts, questions, interview_ended
                )
            )

            await interview_ended.wait()
            t_b2o.cancel()
            t_o2b.cancel()
            await asyncio.gather(t_b2o, t_o2b, return_exceptions=True)

    except Exception as exc:
        logger.error("Realtime proxy error: %s", exc)
        try:
            await browser_ws.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
        return

    if not user_transcripts:
        try:
            await browser_ws.send_json(
                {
                    "type": "error",
                    "message": "수집된 답변이 없습니다. 인터뷰를 다시 시도하세요.",
                }
            )
        except Exception:
            pass
        return

    try:
        await browser_ws.send_json(
            {
                "type": "evaluating",
                "message": f"답변 {len(user_transcripts)}개를 평가하는 중입니다...",
            }
        )
        report = await on_complete(user_transcripts)
        await browser_ws.send_json({"type": "interview.complete", "report": report})
    except Exception as exc:
        logger.error("on_complete error: %s", exc)
        try:
            await browser_ws.send_json(
                {"type": "error", "message": "리포트 생성에 실패했습니다."}
            )
        except Exception:
            pass


async def _configure_session(
    oai_ws: websockets.asyncio.client.ClientConnection, instructions: str
) -> None:
    await oai_ws.send(
        json.dumps(
            {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": instructions,
                    "voice": "shimmer",
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "input_audio_transcription": {"model": "whisper-1"},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 800,
                    },
                    "temperature": 0.8,
                },
            }
        )
    )
    await oai_ws.send(
        json.dumps(
            {
                "type": "response.create",
                "response": {
                    "modalities": ["text", "audio"],
                    "instructions": (
                        "아래 고정 오프닝 질문만 글자 그대로 말하세요. "
                        "다른 인사말, 설명, 질문을 추가하지 마세요.\n\n"
                        f"{OPENING_QUESTION}"
                    ),
                },
            }
        )
    )


async def _browser_to_oai(
    browser_ws: WebSocket,
    oai_ws: websockets.asyncio.client.ClientConnection,
    interview_ended: asyncio.Event,
) -> None:
    try:
        while not interview_ended.is_set():
            msg = await browser_ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes"):
                await oai_ws.send(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(msg["bytes"]).decode(),
                        }
                    )
                )
            elif msg.get("text"):
                data = json.loads(msg["text"])
                if data.get("type") == "interview.end":
                    interview_ended.set()
    except WebSocketDisconnect:
        interview_ended.set()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("browser→oai error: %s", exc)
        interview_ended.set()


async def _oai_to_browser(
    oai_ws: websockets.asyncio.client.ClientConnection,
    browser_ws: WebSocket,
    user_transcripts: list[str],
    questions: list[dict],
    interview_ended: asyncio.Event,
) -> None:
    identity_answer_seen = False
    current_question_index: int | None = None
    try:
        async for raw_msg in oai_ws:
            if interview_ended.is_set():
                break
            event = json.loads(raw_msg)
            etype = event.get("type", "")

            if etype == "response.audio.delta":
                audio = base64.b64decode(event.get("delta", ""))
                if audio:
                    await browser_ws.send_bytes(audio)

            elif etype == "response.audio_transcript.delta":
                await browser_ws.send_json(
                    {"type": "transcript.ai.delta", "text": event.get("delta", "")}
                )

            elif etype == "response.audio_transcript.done":
                ai_text = event.get("transcript", "")
                await browser_ws.send_json(
                    {"type": "transcript.ai.done", "text": ai_text}
                )
                for index, question in enumerate(questions):
                    if str(question.get("question", "")) in ai_text:
                        current_question_index = index
                        break
                if "인터뷰를 마치겠습니다" in ai_text:
                    await asyncio.sleep(1.5)
                    interview_ended.set()

            elif etype == "conversation.item.input_audio_transcription.completed":
                transcript = event.get("transcript", "").strip()
                if transcript:
                    is_identity_answer = not identity_answer_seen
                    if is_identity_answer:
                        identity_answer_seen = True
                        turn_index = None
                    else:
                        if current_question_index is None:
                            current_question_index = len(user_transcripts)
                        turn_index = current_question_index
                        while len(user_transcripts) <= turn_index:
                            user_transcripts.append("")
                        existing = user_transcripts[turn_index]
                        user_transcripts[turn_index] = (
                            f"{existing}\n{transcript}" if existing else transcript
                        )
                    await browser_ws.send_json(
                        {
                            "type": "transcript.user",
                            "text": transcript,
                            "turn_index": turn_index,
                            "is_identity_answer": is_identity_answer,
                        }
                    )
                    if len(user_transcripts) >= len(questions):
                        await browser_ws.send_json(
                            {
                                "type": "info",
                                "message": "모든 질문에 답변하셨습니다. 인터뷰어의 마무리 멘트를 들어주세요.",
                            }
                        )

            elif etype == "input_audio_buffer.speech_started":
                await browser_ws.send_json({"type": "vad.speech_started"})

            elif etype == "input_audio_buffer.speech_stopped":
                await browser_ws.send_json({"type": "vad.speech_stopped"})

            elif etype == "error":
                err = event.get("error", {})
                logger.error("OAI Realtime error: %s", err)
                await browser_ws.send_json(
                    {"type": "error", "message": err.get("message", "오류 발생")}
                )

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("oai→browser error: %s", exc)
    finally:
        interview_ended.set()
