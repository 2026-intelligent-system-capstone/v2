"""학생 인터뷰 진입 라우터.

기본 진입 경로는 단계형(HTTP) 평가 화면이다.
- `/interview/{eval}/{session}/open` — 세션 토큰 입력 → 쿠키 설정 → 단계형 화면으로 redirect
- `/interview/{eval}/{session}` — 단계형 인터뷰 화면 (HTTP API 사용)
- `/interview/{eval}/{session}/voice` — 음성 보조 화면 (선택). 평가 상태머신은
  여전히 HTTP 단계형 core가 권한자다. 음성 transport가 실패해도 단계형 화면에서
  인터뷰를 이어 갈 수 있다.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Request, status, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from openai import AsyncOpenAI

from services.api.app.project_evaluations.persistence.repository import (
    ProjectEvaluationRepository,
)
from services.api.app.project_evaluations.service import ProjectEvaluationService
from services.api.app.project_evaluations.interview.turn_flow import InterviewTurnFlow
from services.api.app.project_evaluations.domain.models import InterviewTurnFlowRequest

router = APIRouter(tags=["realtime-interview"])

logger = logging.getLogger(__name__)


@router.websocket("/interview/{evaluation_id}/{session_id}/ws")
async def interview_websocket(
    websocket: WebSocket,
    evaluation_id: str,
    session_id: str,
):
    """표준 OpenAI Chat API를 활용한 텍스트 전용 인터뷰 프록시."""
    await websocket.accept()
    settings = websocket.app.state.settings
    session_factory = websocket.app.state.session_factory
    client_id = websocket.client.host if websocket.client else "local"

    # 1. 인증 확인
    session_token = websocket.cookies.get(f"interview_session_{session_id}")
    if not session_token:
        logger.warning("WebSocket connection failed: No session token")
        await websocket.close(code=3000, reason="No session token")
        return

    try:
        while True:
            # 프론트엔드로부터 데이터 수신
            data = await websocket.receive_json()
            
            if data["type"] == "transcript":
                text = data["text"]
                mode = data.get("mode", "answer")
                state_data = data.get("state", {})

                # 비즈니스 로직 연동 (DB 업데이트 및 다음 질문 추출)
                with session_factory() as db_session:
                    service = ProjectEvaluationService(ProjectEvaluationRepository(db_session), settings)
                    flow = InterviewTurnFlow(service)
                    flow_resp = flow.submit_answer(
                        evaluation_id,
                        session_id,
                        InterviewTurnFlowRequest(
                            mode=mode,
                            answer_text=text,
                            draft_answer=state_data.get("draftAnswer", ""),
                            follow_up_question=state_data.get("followUpQuestion", ""),
                            follow_up_reason=state_data.get("followUpReason", ""),
                            current_question_id=state_data.get("questionId")
                        ),
                        session_token,
                        client_id
                    )

                # 결과 프론트로 전송 (상태 동기화)
                await websocket.send_json({
                    "type": "flow_response",
                    "payload": flow_resp.model_dump(mode="json")
                })

                # 다음 질문 또는 꼬리질문을 TTS용 텍스트로 전송
                next_text = ""
                if flow_resp.status == "need_follow_up":
                    next_text = flow_resp.follow_up_question
                elif flow_resp.next_question:
                    next_text = flow_resp.next_question.question
                
                if next_text:
                    await websocket.send_json({
                        "type": "text_response",
                        "text": next_text
                    })

            elif data["type"] == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session %s", session_id)
    except Exception as e:
        logger.exception("Unexpected error in interview WebSocket: %s", e)
        if websocket.client_state.name != "DISCONNECTED":
            await websocket.send_json({"type": "error", "message": str(e)})


_STAGED_HTML = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>프로젝트 평가 인터뷰</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0f172a; color: #e2e8f0; font-family: 'Segoe UI', system-ui, sans-serif; min-height: 100vh; padding: 24px 16px; display: flex; flex-direction: column; align-items: center; }
h1 { font-size: 1.4rem; font-weight: 700; color: #7dd3fc; margin-bottom: 4px; }
.subtitle { font-size: .85rem; color: #64748b; margin-bottom: 20px; }
#main { width: 100%; max-width: 820px; display: flex; flex-direction: column; gap: 16px; }
.progress { display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: #1e293b; border-radius: 10px; font-size: .85rem; color: #94a3b8; }
.progress strong { color: #e2e8f0; font-weight: 600; }
.question-card { background: #1e293b; border-radius: 12px; padding: 20px; }
.question-card .label { font-size: .75rem; font-weight: 600; color: #7dd3fc; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 8px; }
.question-card .text { font-size: 1.05rem; line-height: 1.55; color: #e2e8f0; white-space: pre-wrap; }
.follow-up-card { background: #2d1f69; border-radius: 12px; padding: 16px 20px; }
.follow-up-card .label { font-size: .75rem; font-weight: 600; color: #c4b5fd; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 6px; }
.follow-up-card .text { font-size: .95rem; line-height: 1.55; color: #ede9fe; white-space: pre-wrap; }
.info-card { background: #14532d; border-radius: 12px; padding: 14px 18px; color: #d1fae5; font-size: .9rem; line-height: 1.55; display: none; }
.info-card.show { display: block; }
.draft { padding: 10px 14px; background: #0f172a; border: 1px dashed #334155; border-radius: 8px; font-size: .85rem; color: #94a3b8; white-space: pre-wrap; min-height: 1.4rem; }
form { display: flex; flex-direction: column; gap: 10px; }
textarea { width: 100%; min-height: 140px; resize: vertical; padding: 12px 14px; border-radius: 10px; border: 1px solid #334155; background: #0f172a; color: #e2e8f0; font-size: .95rem; font-family: inherit; line-height: 1.5; }
textarea:focus { outline: none; border-color: #7dd3fc; box-shadow: 0 0 0 2px rgba(125,211,252,.25); }
.actions { display: flex; gap: 10px; justify-content: space-between; flex-wrap: wrap; }
.actions .right { display: flex; gap: 10px; }
button { padding: 10px 18px; border: none; border-radius: 8px; font-size: .9rem; font-weight: 600; cursor: pointer; transition: background .15s, opacity .15s; }
button.primary { background: #2563eb; color: #fff; }
button.primary:hover { background: #1d4ed8; }
button.ghost { background: transparent; color: #94a3b8; border: 1px solid #334155; }
button.ghost:hover { color: #e2e8f0; border-color: #7dd3fc; }
button.danger { background: #dc2626; color: #fff; }
button.danger:hover { background: #b91c1c; }
button:disabled { opacity: .55; cursor: default; }
.error { padding: 10px 14px; background: #450a0a; border-radius: 8px; color: #fca5a5; font-size: .85rem; display: none; }
.error.show { display: block; }
#report-view { width: 100%; max-width: 820px; display: none; flex-direction: column; gap: 18px; }
.report-header { padding: 22px; background: #1e293b; border-radius: 14px; text-align: center; }
.verdict { font-size: 1.7rem; font-weight: 800; margin-bottom: 8px; }
.verdict.pass { color: #34d399; }
.verdict.caution { color: #fbbf24; }
.verdict.fail { color: #f87171; }
.score-badge { display: inline-block; padding: 4px 14px; border-radius: 18px; font-size: .92rem; font-weight: 600; background: #0f172a; color: #94a3b8; }
.section { background: #1e293b; border-radius: 12px; padding: 18px; }
.section h3 { font-size: 1rem; font-weight: 700; color: #7dd3fc; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid #1e3a5f; }
.section p { font-size: .9rem; line-height: 1.7; color: #cbd5e1; }
table { width: 100%; border-collapse: collapse; font-size: .85rem; }
th { text-align: left; padding: 8px 10px; background: #0f172a; color: #94a3b8; font-weight: 600; }
td { padding: 8px 10px; border-top: 1px solid #1e3a5f; color: #cbd5e1; vertical-align: top; }
ul.bullet { padding-left: 20px; display: flex; flex-direction: column; gap: 4px; }
ul.bullet li { font-size: .88rem; color: #cbd5e1; line-height: 1.5; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: .75rem; font-weight: 600; }
.tag.pass { background: #14532d; color: #86efac; }
.tag.caution { background: #451a03; color: #fbbf24; }
.tag.fail { background: #450a0a; color: #f87171; }
.muted { color: #64748b; font-size: .82rem; }
.voice-link { font-size: .82rem; color: #7dd3fc; text-decoration: none; }
.voice-link:hover { text-decoration: underline; }
</style>
</head>
<body>
<h1>프로젝트 평가 인터뷰</h1>
<p class="subtitle">질문에 텍스트로 답변하세요. 단계별로 진행됩니다.</p>

<div id="main">
  <div class="progress" id="progress">세션 상태를 불러오는 중입니다...</div>
  <div class="error" id="error"></div>
  <div class="info-card" id="info"></div>
  <div class="question-card" id="question-card" style="display:none">
    <div class="label" id="question-label">질문</div>
    <div class="text" id="question-text"></div>
  </div>
  <div class="follow-up-card" id="follow-up-card" style="display:none">
    <div class="label">꼬리질문</div>
    <div class="text" id="follow-up-text"></div>
  </div>
  <div class="draft" id="draft" style="display:none"></div>
  <form id="answer-form">
    <textarea id="answer" placeholder="여기에 답변을 입력하세요" required></textarea>
    <div class="actions">
      <button type="button" class="danger" id="end-btn">인터뷰 종료</button>
      <div class="right">
        <button type="submit" class="primary" id="submit-btn">답변 제출</button>
      </div>
    </div>
  </form>
  <p class="muted">음성으로 진행하려면 <a class="voice-link" id="voice-link" href="#">음성 인터뷰 화면</a>으로 이동하세요. 음성 transport가 실패해도 이 단계형 화면에서 평가를 이어갈 수 있습니다.</p>
</div>

<div id="report-view"></div>

<script>
const parts = location.pathname.split('/');
const EVAL_ID = parts[2];
const SESSION_ID = parts[3];
const API_BASE = `/api/project-evaluations/${EVAL_ID}/sessions/${SESSION_ID}/interview`;
document.getElementById('voice-link').href = `/interview/${EVAL_ID}/${SESSION_ID}/voice`;

let currentMode = 'answer';
let currentQuestionId = null;
let draftAnswer = '';
let followUpQuestion = '';
let followUpReason = '';
let totalQuestions = 0;

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function showError(text) {
  const node = document.getElementById('error');
  if (!text) {
    node.classList.remove('show');
    node.textContent = '';
    return;
  }
  node.classList.add('show');
  node.textContent = text;
}

function showInfo(text) {
  const node = document.getElementById('info');
  if (!text) {
    node.classList.remove('show');
    node.textContent = '';
    return;
  }
  node.classList.add('show');
  node.textContent = text;
}

function setProgress(text) {
  document.getElementById('progress').innerHTML = text;
}

function renderQuestion(question, total, index) {
  if (!question) {
    document.getElementById('question-card').style.display = 'none';
    return;
  }
  document.getElementById('question-card').style.display = 'block';
  document.getElementById('question-label').textContent = `질문 ${index + 1} / ${total}`;
  document.getElementById('question-text').textContent = question.question || '';
  currentQuestionId = question.id || null;
}

function renderFollowUp(text) {
  const card = document.getElementById('follow-up-card');
  if (!text) {
    card.style.display = 'none';
    return;
  }
  card.style.display = 'block';
  document.getElementById('follow-up-text').textContent = text;
}

function renderDraft(text) {
  const node = document.getElementById('draft');
  if (!text) {
    node.style.display = 'none';
    node.textContent = '';
    return;
  }
  node.style.display = 'block';
  node.textContent = `직전까지 누적된 답변: ${text}`;
}

async function api(method, path, body) {
  const init = {
    method,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
  };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
  }
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    let detail = '';
    try {
      const errPayload = await res.json();
      detail = typeof errPayload.detail === 'string'
        ? errPayload.detail
        : JSON.stringify(errPayload.detail || errPayload);
    } catch (_e) {
      detail = await res.text();
    }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.json();
}

async function refreshState() {
  showError('');
  try {
    const state = await api('GET', '/state');
    totalQuestions = state.total_questions || 0;
    if (state.is_completed) {
      try {
        await api('POST', '/complete', undefined);
      } catch (_e) {
        // ignore — redirect 후 Streamlit이 idempotent complete를 재호출한다.
      }
      goToReport();
      return;
    }
    setProgress(`<strong>${state.current_question_index + 1}</strong> / ${state.total_questions} 질문 진행 중`);
    renderQuestion(state.question, state.total_questions, state.current_question_index);
    renderFollowUp('');
    renderDraft('');
    currentMode = 'answer';
    draftAnswer = '';
    followUpQuestion = '';
    followUpReason = '';
  } catch (err) {
    showError(err.message);
  }
}

async function submitAnswer(text, modeOverride) {
  const mode = modeOverride || currentMode;
  const payload = {
    mode,
    answer_text: text,
    draft_answer: draftAnswer,
    follow_up_question: followUpQuestion,
    follow_up_reason: followUpReason,
    current_question_id: currentQuestionId,
  };
  return api('POST', '/answer', payload);
}

function applyFlowResponse(response) {
  draftAnswer = response.draft_answer || '';
  followUpQuestion = response.follow_up_question || '';
  followUpReason = response.follow_up_reason || '';

  if (response.status === 'need_follow_up') {
    currentMode = 'follow_up';
    renderDraft(draftAnswer);
    renderFollowUp(followUpQuestion);
    showInfo(response.message || '꼬리질문에 답변해 주세요.');
    document.getElementById('answer').value = '';
    document.getElementById('answer').focus();
    return;
  }

  draftAnswer = '';
  followUpQuestion = '';
  followUpReason = '';

  if (response.status === 'turn_submitted') {
    currentMode = 'answer';
    showInfo(response.message || '');
    refreshState();
    return;
  }

  if (response.status === 'ready_to_complete' || response.status === 'completed') {
    finalizeAndRender();
  }
}

function goToReport() {
  window.location.href = `/interview/${EVAL_ID}/${SESSION_ID}/report-redirect`;
}

async function finalizeAndRender() {
  try {
    await api('POST', '/complete', undefined);
  } catch (err) {
    // 이미 완료된 세션이면 server가 기존 리포트를 그대로 반환하므로 무시 가능.
    // 그 외 오류는 노출하지만 리포트 화면으로는 그래도 이동시킨다.
    showError(err.message);
  }
  goToReport();
}

document.getElementById('answer-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  showError('');
  const textarea = document.getElementById('answer');
  const text = textarea.value.trim();
  if (!text) {
    showError('답변을 입력하세요.');
    return;
  }
  const submitBtn = document.getElementById('submit-btn');
  submitBtn.disabled = true;
  try {
    const response = await submitAnswer(text);
    applyFlowResponse(response);
  } catch (err) {
    showError(err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

document.getElementById('end-btn').addEventListener('click', async () => {
  if (!confirm('인터뷰를 종료하시겠습니까? 남은 질문은 미응답으로 처리되고, 지금까지의 답변으로 리포트가 작성됩니다.')) {
    return;
  }
  showError('');
  const endBtn = document.getElementById('end-btn');
  endBtn.disabled = true;
  try {
    await api('POST', '/abort', undefined);
  } catch (err) {
    endBtn.disabled = false;
    showError(err.message);
    return;
  }
  goToReport();
});

refreshState();
</script>
</body>
</html>
"""


_VOICE_HTML = r'''
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>음성 인터뷰 (OpenAI Realtime)</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0f172a; color: #e2e8f0; font-family: 'Segoe UI', system-ui, sans-serif; min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 24px 16px; }
h1 { font-size: 1.4rem; font-weight: 700; color: #7dd3fc; margin-bottom: 4px; }
.subtitle { font-size: .85rem; color: #64748b; margin-bottom: 20px; }
#main { width: 100%; max-width: 820px; display: flex; flex-direction: column; gap: 16px; }
.progress { display: flex; align-items: center; gap: 14px; padding: 10px 14px; background: #1e293b; border-radius: 10px; font-size: .85rem; color: #94a3b8; flex-wrap: wrap; }
.progress strong { color: #e2e8f0; font-weight: 600; }
.progress-dots { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.dot { width: 14px; height: 14px; border-radius: 50%; border: 1px solid #475569; background: transparent; transition: background .15s, border-color .15s, box-shadow .15s; }
.dot.done { background: #34d399; border-color: #34d399; }
.dot.current { background: #7dd3fc; border-color: #7dd3fc; box-shadow: 0 0 0 3px rgba(125,211,252,.25); }
.dot.pending { background: transparent; border-color: #475569; }
.dash { color: #475569; user-select: none; font-size: .85rem; }
.progress-summary { font-size: .85rem; color: #94a3b8; margin-left: auto; }
.status-bar { display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: #1e293b; border-radius: 10px; }
.status-dot { width: 12px; height: 12px; border-radius: 50%; background: #64748b; flex-shrink: 0; transition: background .3s; }
.status-dot.idle { background: #64748b; }
.status-dot.connected { background: #34d399; }
.status-dot.speaking { background: #34d399; animation: pulse .8s infinite; }
.status-dot.recording { background: #f87171; animation: pulse .5s infinite; }
.status-dot.transcribing { background: #a78bfa; animation: pulse 1s infinite; }
.status-dot.error { background: #ef4444; }
.status-text { font-size: .9rem; color: #94a3b8; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .4; } }
.question-card { background: #1e293b; border-radius: 12px; padding: 20px; }
.question-card .label { font-size: .75rem; font-weight: 600; color: #7dd3fc; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 8px; }
.question-card .text { font-size: 1.05rem; line-height: 1.55; color: #e2e8f0; white-space: pre-wrap; }
.follow-up-card { background: #2d1f69; border-radius: 12px; padding: 16px 20px; display: none; }
.follow-up-card.show { display: block; }
.info-card { background: #14532d; border-radius: 12px; padding: 12px 16px; color: #d1fae5; font-size: .88rem; line-height: 1.55; display: none; }
.info-card.show { display: block; }
.transcript-area { display: flex; flex-direction: column; gap: 8px; }
textarea { width: 100%; min-height: 110px; resize: vertical; padding: 12px 14px; border-radius: 10px; border: 1px solid #334155; background: #0f172a; color: #e2e8f0; font-size: .95rem; font-family: inherit; line-height: 1.5; }
.actions { display: flex; gap: 10px; justify-content: space-between; flex-wrap: wrap; align-items: center; }
button { padding: 10px 18px; border: none; border-radius: 8px; font-size: .9rem; font-weight: 600; cursor: pointer; transition: background .15s, opacity .15s; }
button.primary { background: #2563eb; color: #fff; }
button.record { background: #16a34a; color: #fff; }
button.record.recording { background: #dc2626; }
button.ghost { background: transparent; color: #94a3b8; border: 1px solid #334155; }
button.danger { background: #dc2626; color: #fff; }
button:disabled { opacity: .45; cursor: default; }
.error { padding: 10px 14px; background: #450a0a; border-radius: 8px; color: #fca5a5; font-size: .85rem; display: none; }
.error.show { display: block; }
</style>
</head>
<body>
<h1>음성 인터뷰</h1>
<p class="subtitle">OpenAI Realtime SDK Proxy (Text-only) + Client STT/TTS</p>

<div id="main">
  <div class="progress" id="progress">
    <div class="progress-dots" id="progress-dots"></div>
    <span class="progress-summary" id="progress-summary">연결 중...</span>
  </div>
  <div class="status-bar">
    <div class="status-dot idle" id="status-dot"></div>
    <span class="status-text" id="status-text">서버 연결 중</span>
  </div>
  <div class="error" id="error"></div>
  <div class="info-card" id="info"></div>
  
  <div class="question-card" id="question-card" style="display:none">
    <div class="label" id="question-label">질문</div>
    <div class="text" id="question-text"></div>
  </div>
  <div class="follow-up-card" id="follow-up-card">
    <div class="label">꼬리질문</div>
    <div class="text" id="follow-up-text"></div>
  </div>

  <div class="actions">
    <div class="left">
      <button type="button" class="ghost" id="replay-btn" disabled>다시 듣기</button>
    </div>
    <div class="right">
      <button type="button" class="record" id="record-btn" disabled>녹음 시작</button>
    </div>
  </div>

  <div class="transcript-area">
    <textarea id="answer" placeholder="음성 인식이 시작되면 여기에 텍스트가 표시됩니다."></textarea>
    <div class="actions">
      <div class="left">
        <button type="button" class="danger" id="end-btn">종료</button>
      </div>
      <div class="right">
        <button type="button" class="primary" id="submit-btn" disabled>확정 제출</button>
      </div>
    </div>
  </div>
  
  <audio id="tts-audio" preload="auto"></audio>
</div>

<script>
const parts = location.pathname.split('/');
const EVAL_ID = parts[2];
const SESSION_ID = parts[3];
const API_BASE = `/api/project-evaluations/${EVAL_ID}/sessions/${SESSION_ID}/interview`;
const WS_PROTOCOL = location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_URL = `${WS_PROTOCOL}//${location.host}/interview/${EVAL_ID}/${SESSION_ID}/ws`;

const state = {
  mode: 'answer',
  questionId: null,
  questionText: '',
  draftAnswer: '',
  followUpQuestion: '',
  followUpReason: '',
  totalQuestions: 0,
  currentIndex: 0,
};

let socket = null;
let recognition = null;
let isRecording = false;

const ttsAudio = document.getElementById('tts-audio');

// 오디오 재생 종료 시 상태 복구
ttsAudio.onended = () => {
  console.debug("TTS Playback ended");
  setStatus('idle', '대기 중');
  readyForRecording();
};

// 1. WebSocket 초기화 및 에러 로깅 강화
function initWebSocket() {
  console.log("Connecting to WebSocket:", WS_URL);
  socket = new WebSocket(WS_URL);

  socket.onopen = () => {
    console.log("WebSocket connected.");
    setStatus('connected', '서버 연결 완료');
    refreshState();
  };

  socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.debug("WS Message received:", data);

    if (data.type === 'text_response') {
      // 텍스트가 도착하자마자 즉시 TTS 요청 시작
      playTts(data.text);
    } else if (data.type === 'flow_response') {
      applyFlowResponse(data.payload);
    } else if (data.type === 'error') {
      showError("Server error: " + data.message);
    }
  };

  socket.onerror = (error) => {
    console.error("WebSocket Error:", error);
    showError("WebSocket 통신 오류가 발생했습니다.");
  };

  socket.onclose = (event) => {
    let reason = "Unknown reason";
    if (event.code === 1000) reason = "Normal Closure";
    else if (event.code === 1001) reason = "Going Away";
    else if (event.code === 1006) reason = "Abnormal Closure (Network lost)";
    else if (event.code === 3000) reason = "Authentication Failed (No session token)";
    else if (event.code === 3001) reason = "Invalid Session";
    
    console.warn(`WebSocket closed. Code: ${event.code}, Reason: ${reason}`);
    setStatus('error', `연결 종료: ${reason}`);
    
    if (event.code !== 1000 && event.code !== 3000) {
      setTimeout(initWebSocket, 3000); // 자동 재연결 시도
    }
  };
}

// 2. Client-side STT (Web Speech API)
function initSTT() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    showError("이 브라우저는 음성 인식을 지원하지 않습니다.");
    return;
  }
  recognition = new SpeechRecognition();
  recognition.lang = 'ko-KR';
  recognition.interimResults = true;
  recognition.continuous = true;

  recognition.onstart = () => {
    isRecording = true;
    setStatus('recording', '녹음 중... 말씀해 주세요.');
    updateButtons();
  };

  recognition.onresult = (event) => {
    let interimTranscript = '';
    let finalTranscript = '';
    for (let i = event.resultIndex; i < event.results.length; ++i) {
      if (event.results[i].isFinal) {
        finalTranscript += event.results[i][0].transcript;
      } else {
        interimTranscript += event.results[i][0].transcript;
      }
    }
    document.getElementById('answer').value = finalTranscript || interimTranscript;
    syncSubmitButton();
  };

  recognition.onerror = (event) => {
    console.error("STT Error:", event.error);
    showError("음성 인식 오류: " + event.error);
    stopRecording();
  };

  recognition.onend = () => {
    isRecording = false;
    updateButtons();
    if (statusText() === '녹음 중... 말씀해 주세요.') {
        setStatus('idle', '녹음 종료');
    }
  };
}

// 3. Backend High-Quality TTS API (Ultra-low Latency Streaming)
async function playTts(text) {
  if (!text) return;
  
  // 기존 재생 중지
  try { 
    ttsAudio.pause(); 
    ttsAudio.src = "";
    ttsAudio.load();
  } catch(e) {}
  
  setStatus('speaking', '인터뷰어가 말하는 중...');
  document.getElementById('record-btn').disabled = true;
  document.getElementById('replay-btn').disabled = true;
  
  try {
    const response = await fetch(`${API_BASE}/tts`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    
    // 스트리밍 재생을 위해 MediaSource 사용
    if (window.MediaSource) {
      const mediaSource = new MediaSource();
      ttsAudio.src = URL.createObjectURL(mediaSource);

      mediaSource.addEventListener('sourceopen', async () => {
        const sourceBuffer = mediaSource.addSourceBuffer('audio/mpeg');
        const reader = response.body.getReader();
        
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) {
              if (mediaSource.readyState === 'open') mediaSource.endOfStream();
              break;
            }
            sourceBuffer.appendBuffer(value);
            await new Promise(r => sourceBuffer.onupdateend = r);
            
            if (ttsAudio.paused) {
              ttsAudio.play().catch(e => console.debug("Auto-play wait:", e));
            }
          }
        } catch (err) {
          console.error("Streaming reader error:", err);
          if (mediaSource.readyState === 'open') mediaSource.endOfStream();
        }
      });
    } else {
      // Fallback: MediaSource 미지원 시 Blob 방식
      const blob = await response.blob();
      ttsAudio.src = URL.createObjectURL(blob);
      await ttsAudio.play();
    }

  } catch (err) {
    console.error("TTS Error:", err);
    showError("음성 합성 실패: " + err.message);
    setStatus('idle', '대기 중');
    readyForRecording();
  }
}

// UI Helpers
function setStatus(kind, text) {
  document.getElementById('status-dot').className = 'status-dot ' + kind;
  document.getElementById('status-text').textContent = text;
}
function statusText() { return document.getElementById('status-text').textContent; }
function showError(text) {
  const node = document.getElementById('error');
  node.textContent = text;
  node.classList.toggle('show', !!text);
}
function showInfo(text) {
  const node = document.getElementById('info');
  node.textContent = text;
  node.classList.toggle('show', !!text);
}
function renderQuestion(text, index, total) {
  const card = document.getElementById('question-card');
  card.style.display = text ? 'block' : 'none';
  document.getElementById('question-label').textContent = `질문 ${index + 1} / ${total}`;
  document.getElementById('question-text').textContent = text;
}
function renderFollowUp(text) {
  const card = document.getElementById('follow-up-card');
  card.classList.toggle('show', !!text);
  document.getElementById('follow-up-text').textContent = text;
}
function updateButtons() {
  const btn = document.getElementById('record-btn');
  btn.disabled = false;
  btn.textContent = isRecording ? '녹음 종료' : '녹음 시작';
  btn.classList.toggle('recording', isRecording);
}
function syncSubmitButton() {
  document.getElementById('submit-btn').disabled = !document.getElementById('answer').value.trim();
}

// Logic
function startRecording() {
  try { ttsAudio.pause(); } catch(e) {}
  if (recognition) recognition.start();
}
function stopRecording() {
  if (recognition) recognition.stop();
}

async function refreshState() {
  try {
    const res = await fetch(`${API_BASE}/state`, { credentials: 'same-origin' });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`상태를 불러올 수 없습니다 (HTTP ${res.status}): ${text}`);
    }
    const data = await res.json();
    state.totalQuestions = data.total_questions || 0;
    state.currentIndex = data.current_question_index || 0;
    if (data.is_completed) { 
      window.location.href = location.pathname.replace('/voice', '/report-redirect'); 
      return; 
    }
    
    state.questionId = data.question?.id;
    state.questionText = data.question?.question || '';
    renderQuestion(state.questionText, state.currentIndex, state.totalQuestions);
    
    if (state.questionText) {
      playTts(state.questionText);
    }
  } catch (err) {
    console.error("refreshState error:", err);
    showError(err.message);
    setStatus('error', '질문 로딩 실패');
  }
}

function applyFlowResponse(payload) {
  state.draftAnswer = payload.draft_answer || '';
  state.followUpQuestion = payload.follow_up_question || '';
  state.followUpReason = payload.follow_up_reason || '';

  if (payload.status === 'need_follow_up') {
    state.mode = 'follow_up';
    renderFollowUp(state.followUpQuestion);
    playTts(state.followUpQuestion);
  } else if (payload.status === 'turn_submitted') {
    state.mode = 'answer';
    renderFollowUp('');
    document.getElementById('answer').value = '';
    refreshState();
  } else if (payload.status === 'ready_to_complete' || payload.status === 'completed') {
    window.location.href = location.pathname.replace('/voice', '/report-redirect');
  }
}

// Event Listeners
document.getElementById('record-btn').addEventListener('click', () => {
  if (isRecording) stopRecording(); else startRecording();
});

document.getElementById('submit-btn').addEventListener('click', () => {
  const text = document.getElementById('answer').value.trim();
  if (!text) return;
  socket.send(json({ type: 'transcript', text, mode: state.mode, state }));
  setStatus('transcribing', '제출 중...');
  document.getElementById('submit-btn').disabled = true;
});

document.getElementById('replay-btn').addEventListener('click', () => {
  playTts(state.mode === 'follow_up' ? state.followUpQuestion : state.questionText);
});

document.getElementById('end-btn').addEventListener('click', () => {
  if (confirm('종료하시겠습니까?')) window.location.href = location.pathname.replace('/voice', '/report-redirect');
});

function json(obj) { return JSON.stringify(obj); }
function readyForRecording() { document.getElementById('record-btn').disabled = false; document.getElementById('replay-btn').disabled = false; }

initWebSocket();
initSTT();
</script>
</body>
</html>
'''

# 외부 import 호환용 (테스트 등이 음성 보조 HTML을 검사할 때 사용한다)
_HTML = _VOICE_HTML


@router.get("/interview/{evaluation_id}/{session_id}/open", response_class=HTMLResponse)
async def open_interview_page(evaluation_id: str, session_id: str) -> str:
    return (
        "<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>인터뷰 입장</title></head><body>"
        "<form method='post'>"
        "<p>인터뷰 세션을 시작합니다.</p>"
        "<input type='password' name='session_token' placeholder='세션 토큰' required autofocus>"
        "<button type='submit'>인터뷰 시작</button>"
        "</form></body></html>"
    )


@router.post("/interview/{evaluation_id}/{session_id}/open")
async def set_interview_cookie(
    request: Request,
    evaluation_id: str,
    session_id: str,
    session_token: str = Form(...),
) -> RedirectResponse:
    settings = request.app.state.settings
    session_factory = request.app.state.session_factory
    client_id = request.client.host if request.client else "local"
    with session_factory() as db_session:
        service = ProjectEvaluationService(
            ProjectEvaluationRepository(db_session),
            settings,
        )
        service.ensure_session(evaluation_id, session_id, session_token, client_id)

    response = RedirectResponse(
        f"/interview/{evaluation_id}/{session_id}/voice", status_code=303
    )
    response.set_cookie(
        key=f"interview_session_{session_id}",
        value=session_token,
        httponly=True,
        samesite="strict",
        max_age=60 * 60 * 2,
        secure=request.url.scheme == "https",
    )
    return response


@router.get("/interview/{evaluation_id}/{session_id}/enter")
async def enter_interview(
    request: Request,
    evaluation_id: str,
    session_id: str,
    session_token: str,
) -> RedirectResponse:
    settings = request.app.state.settings
    session_factory = request.app.state.session_factory
    client_id = request.client.host if request.client else "local"
    with session_factory() as db_session:
        service = ProjectEvaluationService(
            ProjectEvaluationRepository(db_session),
            settings,
        )
        service.ensure_session(evaluation_id, session_id, session_token, client_id)

    response = RedirectResponse(
        f"/interview/{evaluation_id}/{session_id}/voice", status_code=303
    )
    response.set_cookie(
        key=f"interview_session_{session_id}",
        value=session_token,
        httponly=True,
        samesite="strict",
        max_age=60 * 60 * 2,
        secure=request.url.scheme == "https",
    )
    return response


@router.get("/interview/{evaluation_id}/{session_id}", response_class=HTMLResponse)
async def get_staged_interview_page(evaluation_id: str, session_id: str) -> str:
    return _STAGED_HTML


@router.get("/interview/{evaluation_id}/{session_id}/voice", response_class=HTMLResponse)
async def get_voice_interview_page(evaluation_id: str, session_id: str) -> str:
    return _VOICE_HTML


@router.get("/interview/{evaluation_id}/{session_id}/report-redirect")
async def redirect_to_streamlit_report(
    request: Request,
    evaluation_id: str,
    session_id: str,
) -> RedirectResponse:
    """인터뷰 완료 후 학생을 Streamlit 리포트 페이지로 보내는 경로.

    `interview_session_{session_id}` 쿠키에서 세션 토큰을 읽어
    Streamlit URL 쿼리에 동봉한다. 쿠키는 httponly여서 JS로는 읽을 수 없으므로
    이 서버측 redirect가 토큰 전달 경로 역할을 한다.
    """
    session_token = request.cookies.get(f"interview_session_{session_id}")
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="인터뷰 세션 토큰이 없습니다. 다시 입장해 주세요.",
        )
    settings = request.app.state.settings
    base_url = settings.PUBLIC_STREAMLIT_BASE_URL.rstrip("/")
    query = urlencode(
        {
            "mode": "student_report",
            "evaluation_id": evaluation_id,
            "session_id": session_id,
            "session_token": session_token,
        }
    )
    return RedirectResponse(f"{base_url}/?{query}", status_code=303)

