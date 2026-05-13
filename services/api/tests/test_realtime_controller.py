from __future__ import annotations

import pytest

from services.api.app.project_evaluations.interview.intent_classifier import (
    StudentIntent,
)
from services.api.app.project_evaluations.realtime.controller import (
    RealtimeInterviewController,
    RealtimeInterviewState,
)


@pytest.fixture()
def questions() -> list[dict[str, str]]:
    return [
        {"question": "첫 번째 질문", "intent": "구현 이해"},
        {"question": "두 번째 질문", "intent": "설계 이해"},
    ]


def test_identity_answer_is_not_added_to_evaluation_answers(
    questions: list[dict[str, str]],
) -> None:
    controller = RealtimeInterviewController(questions)

    controller.begin_opening()
    controller.handle_playback_done()
    action = controller.handle_user_transcript(
        "20201234 홍길동", intent=StudentIntent.ANSWER
    )

    assert controller.identity_answer_seen is True
    assert controller.answers == []
    assert controller.state == RealtimeInterviewState.ASKING_QUESTION
    assert action.browser_messages[0]["is_identity_answer"] is True


def test_answer_extra_and_decline_are_collapsed_into_one_answer(
    questions: list[dict[str, str]],
) -> None:
    controller = RealtimeInterviewController(questions)
    controller.begin_opening()
    controller.handle_playback_done()
    controller.handle_user_transcript("20201234 홍길동", intent=StudentIntent.ANSWER)
    controller.handle_playback_done()

    controller.handle_user_transcript("본문 답변", intent=StudentIntent.ANSWER)
    controller.handle_playback_done()
    controller.handle_user_transcript(
        "추가 답변", decline_response=False, intent=StudentIntent.ANSWER
    )
    controller.handle_playback_done()
    controller.handle_user_transcript(
        "없습니다", decline_response=True, intent=StudentIntent.ANSWER
    )

    assert controller.answers == ["본문 답변\n추가 답변"]
    assert controller.question_index == 1
    assert controller.state == RealtimeInterviewState.ASKING_QUESTION


def test_skip_intent_stores_skipped_answer(questions: list[dict[str, str]]) -> None:
    controller = RealtimeInterviewController(questions)
    controller.begin_opening()
    controller.handle_playback_done()
    controller.handle_user_transcript("20201234 홍길동", intent=StudentIntent.ANSWER)
    controller.handle_playback_done()

    action = controller.handle_user_transcript(
        "넘어가겠습니다", intent=StudentIntent.SKIP
    )

    assert controller.answers == ["(건너뜀)"]
    assert controller.question_index == 1
    assert controller.state == RealtimeInterviewState.ASKING_QUESTION
    assert action.browser_messages[0]["intent"] == "skip"
    assert action.browser_messages[0]["is_skip"] is True


def test_end_exam_intent_fills_unanswered_questions(
    questions: list[dict[str, str]],
) -> None:
    controller = RealtimeInterviewController(questions)
    controller.begin_opening()
    controller.handle_playback_done()
    controller.handle_user_transcript("20201234 홍길동", intent=StudentIntent.ANSWER)
    controller.handle_playback_done()
    controller.handle_user_transcript("첫 답변", intent=StudentIntent.ANSWER)
    controller.handle_playback_done()

    action = controller.handle_user_transcript(
        "시험을 종료하겠습니다", intent=StudentIntent.END_EXAM
    )

    assert controller.answers == ["첫 답변", "(미응답)"]
    assert controller.question_index == 2
    assert controller.state == RealtimeInterviewState.CLOSING
    assert action.browser_messages[0]["intent"] == "end_exam"
    assert action.browser_messages[0]["is_end_exam"] is True


def test_interview_end_button_uses_end_exam_policy(
    questions: list[dict[str, str]],
) -> None:
    controller = RealtimeInterviewController(questions)
    controller.begin_opening()
    controller.handle_playback_done()
    controller.handle_user_transcript("20201234 홍길동", intent=StudentIntent.ANSWER)
    controller.handle_playback_done()

    controller.handle_end_exam_request()

    assert controller.answers == ["(미응답)", "(미응답)"]
    assert controller.state == RealtimeInterviewState.CLOSING


def test_more_timeout_completes_current_answer(questions: list[dict[str, str]]) -> None:
    controller = RealtimeInterviewController(questions)
    controller.begin_opening()
    controller.handle_playback_done()
    controller.handle_user_transcript("20201234 홍길동", intent=StudentIntent.ANSWER)
    controller.handle_playback_done()
    controller.handle_user_transcript("본문 답변", intent=StudentIntent.ANSWER)
    controller.handle_playback_done()

    controller.handle_input_timeout("more")

    assert controller.answers == ["본문 답변"]
    assert controller.question_index == 1
    assert controller.state == RealtimeInterviewState.ASKING_QUESTION
