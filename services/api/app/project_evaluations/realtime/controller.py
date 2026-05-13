"""Realtime UX/transport controller.

평가 상태머신 권한은 `interview/turn_flow.py`에 있다. 이 모듈은 오직
브라우저 입력 모드, TTS 재생 동기화, 음성 전사 카운트만 관리한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

OPENING_QUESTION = (
    "안녕하세요, 지금부터 프로젝트 평가를 진행하겠습니다. 프로젝트 평가란, "
    "학생분께서 제출한 자료를 바탕으로 이 프로젝트를 실제로 본인이 했는지, "
    "했다면 어느정도 수준까지 이해하고 있는지 확인하는 과정입니다. "
    "우선, 본인의 학번과 이름을 말씀해주세요."
)
CLOSING_MESSAGE = "인터뷰를 마치겠습니다. 수고하셨습니다."


class VoiceInputMode(StrEnum):
    IDENTITY = "identity"
    ANSWER = "answer"
    MORE = "more"
    FOLLOW_UP = "follow_up"


_INPUT_PROMPT: dict[VoiceInputMode, dict[str, object]] = {
    VoiceInputMode.IDENTITY: {"timeout_seconds": 60, "message": "답변을 말씀해 주세요"},
    VoiceInputMode.ANSWER: {"timeout_seconds": 60, "message": "답변을 말씀해 주세요"},
    VoiceInputMode.MORE: {"timeout_seconds": 15, "message": "추가 답변을 말씀해 주세요"},
    VoiceInputMode.FOLLOW_UP: {
        "timeout_seconds": 45,
        "message": "꼬리질문에 답변해 주세요",
    },
}


@dataclass(slots=True)
class RealtimeControllerAction:
    browser_messages: list[dict[str, object]] = field(default_factory=list)
    prompt_text: str | None = None


class RealtimeUxController:
    """음성 UX/transport 상태만 관리한다.

    - 평가 상태머신(질문 인덱스, 답변 누적, 종료 결정 등)은 가지지 않는다.
    - 평가 결정은 `InterviewTurnFlow` 응답에 따라 외부에서 주입한다.
    """

    def __init__(self) -> None:
        self.pending_input_mode: VoiceInputMode | None = None
        self.input_open = False
        self.awaiting_playback_done = False
        self.closing = False
        self._committed_count = 0
        self._processed_transcription_count = 0

    @property
    def transcription_count(self) -> int:
        return self._processed_transcription_count

    def has_pending_transcription(self) -> bool:
        return self._committed_count > self._processed_transcription_count

    def queue_prompt(
        self,
        text: str,
        next_input_mode: VoiceInputMode | None,
        *,
        closing: bool = False,
    ) -> RealtimeControllerAction:
        """다음 TTS 멘트를 큐에 넣고, 재생이 끝나면 어떤 input 모드를 열지 기록."""
        self.pending_input_mode = None if closing else next_input_mode
        self.closing = closing
        self.awaiting_playback_done = True
        self.input_open = False
        return RealtimeControllerAction(prompt_text=text)

    def queue_opening(self) -> RealtimeControllerAction:
        return self.queue_prompt(OPENING_QUESTION, VoiceInputMode.IDENTITY)

    def queue_closing(self) -> RealtimeControllerAction:
        return self.queue_prompt(CLOSING_MESSAGE, None, closing=True)

    def handle_playback_done(self) -> RealtimeControllerAction:
        self.awaiting_playback_done = False
        self.input_open = False
        if self.closing:
            return RealtimeControllerAction()
        mode = self.pending_input_mode
        if mode is None:
            return RealtimeControllerAction()
        self.input_open = True
        prompt = _INPUT_PROMPT[mode]
        return RealtimeControllerAction(
            browser_messages=[
                {
                    "type": "input.open",
                    "mode": mode.value,
                    "timeout_seconds": prompt["timeout_seconds"],
                    "message": prompt["message"],
                }
            ]
        )

    def close_input(self) -> None:
        self.input_open = False

    def handle_input_committed(self) -> None:
        self._committed_count += 1

    def handle_transcription_completed(self) -> None:
        self._processed_transcription_count += 1

    def handle_transcription_failed(self) -> RealtimeControllerAction:
        self._processed_transcription_count += 1
        return RealtimeControllerAction(
            browser_messages=[
                {
                    "type": "transcription.failed",
                    "transcription_count": self._processed_transcription_count,
                    "message": "음성 전사에 실패했습니다. 다시 말씀해 주세요.",
                }
            ]
        )
