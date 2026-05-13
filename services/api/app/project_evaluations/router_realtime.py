"""Browser interview routes."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from services.api.app.project_evaluations.persistence.repository import (
    ProjectEvaluationRepository,
)
from services.api.app.project_evaluations.service import ProjectEvaluationService

router = APIRouter(tags=["step-interview"])

# ---------------------------------------------------------------------------
# HTML interview page
# NOTE: plain string — NOT an f-string.  CSS and JS use literal { } braces.
#       IDs are extracted from window.location.pathname in JS (no substitution).
# ---------------------------------------------------------------------------

_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>단계형 프로젝트 인터뷰</title>
<style>
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background: radial-gradient(circle at top left, #1e3a8a 0, #0f172a 32rem);
  color: #e2e8f0;
  font-family: Inter, "Segoe UI", system-ui, sans-serif;
  padding: 28px 16px 48px;
}
main, #report-view { width: min(920px, 100%); margin: 0 auto; }
header { margin-bottom: 22px; }
h1 { margin: 0 0 8px; color: #bae6fd; font-size: clamp(1.7rem, 4vw, 2.7rem); }
.subtitle { margin: 0; color: #94a3b8; line-height: 1.6; }
.panel {
  background: rgba(15, 23, 42, .86);
  border: 1px solid rgba(148, 163, 184, .22);
  border-radius: 18px;
  box-shadow: 0 20px 70px rgba(2, 6, 23, .35);
  padding: 22px;
}
#status-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
#status-dot { width: 12px; height: 12px; border-radius: 50%; background: #64748b; }
#status-dot.ready { background: #22c55e; }
#status-dot.busy { background: #a78bfa; animation: pulse 1s infinite; }
#status-dot.error { background: #ef4444; }
#status-text { color: #cbd5e1; font-size: .95rem; }
.error-card {
  display: grid;
  gap: 10px;
  margin-bottom: 16px;
  padding: 14px;
  border-radius: 14px;
  border: 1px solid rgba(248, 113, 113, .4);
  background: rgba(127, 29, 29, .26);
}
.error-card strong { color: #fecaca; }
.error-card p { margin: 0; color: #fee2e2; line-height: 1.5; white-space: pre-wrap; }
.error-card[hidden] { display: none; }
.error-actions { display: flex; justify-content: flex-end; }
@keyframes pulse { 50% { opacity: .42; } }
.progress { color: #7dd3fc; font-size: .86rem; font-weight: 700; margin-bottom: 10px; }
.question-card {
  background: linear-gradient(135deg, rgba(14, 165, 233, .18), rgba(59, 130, 246, .08));
  border: 1px solid rgba(125, 211, 252, .24);
  border-radius: 16px;
  padding: 18px;
  margin-bottom: 16px;
}
.question-card h2 { margin: 0 0 10px; font-size: 1.25rem; color: #f8fafc; line-height: 1.45; }
.question-meta { color: #93c5fd; font-size: .86rem; line-height: 1.5; }
#turn-history { display: grid; gap: 10px; margin-bottom: 16px; }
.turn {
  border-left: 3px solid #38bdf8;
  background: rgba(30, 41, 59, .72);
  border-radius: 12px;
  padding: 12px 14px;
}
.turn strong { display: block; color: #bfdbfe; margin-bottom: 6px; }
.turn p { margin: 0; color: #dbeafe; white-space: pre-wrap; line-height: 1.55; }
.prompt-box {
  display: none;
  background: rgba(67, 56, 202, .22);
  border: 1px solid rgba(167, 139, 250, .32);
  border-radius: 14px;
  padding: 14px;
  margin-bottom: 14px;
  color: #ddd6fe;
  line-height: 1.5;
}
textarea {
  width: 100%;
  min-height: 150px;
  resize: vertical;
  border-radius: 16px;
  border: 1px solid #334155;
  background: #020617;
  color: #e2e8f0;
  padding: 14px;
  font: inherit;
  line-height: 1.6;
}
textarea:focus, button:focus-visible, input:focus-visible { outline: 3px solid rgba(125, 211, 252, .35); }
.audio-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px;
  align-items: center;
  margin: 12px 0;
}
input[type="file"] {
  width: 100%;
  border: 1px dashed #475569;
  border-radius: 12px;
  padding: 10px;
  color: #cbd5e1;
}
.controls { display: flex; flex-wrap: wrap; gap: 10px; justify-content: flex-end; margin-top: 14px; }
button {
  border: 0;
  border-radius: 999px;
  padding: 10px 18px;
  font-weight: 800;
  cursor: pointer;
  color: #0f172a;
  background: #7dd3fc;
}
button.secondary { background: #c4b5fd; }
button.danger { background: #fca5a5; }
button.ghost { background: #334155; color: #e2e8f0; }
button:disabled { opacity: .46; cursor: not-allowed; }
#report-view { display: none; flex-direction: column; gap: 16px; }
.report-header, .section { background: rgba(15, 23, 42, .88); border-radius: 16px; padding: 20px; border: 1px solid #1e3a5f; }
.verdict { font-size: 1.8rem; font-weight: 900; margin-bottom: 8px; }
.verdict.pass { color: #34d399; }
.verdict.caution { color: #fbbf24; }
.verdict.fail { color: #f87171; }
.score-badge { color: #cbd5e1; font-weight: 700; }
.section h3 { margin: 0 0 12px; color: #7dd3fc; }
.section p, .section li { color: #cbd5e1; line-height: 1.65; }
.grid2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
@media (max-width: 720px) {
  body { padding-inline: 12px; }
  .panel { padding: 16px; }
  .grid2, .audio-row { grid-template-columns: 1fr; }
  .controls { justify-content: stretch; }
  button { width: 100%; }
}
</style>
</head>
<body>
<main id="main">
  <header>
    <h1>프로젝트 수행 진위 평가 — 단계형 인터뷰</h1>
    <p class="subtitle">질문을 확인한 뒤 텍스트로 답변하세요. 필요하면 녹음 파일을 업로드해 답변 칸에 전사할 수 있습니다.</p>
  </header>
  <section class="panel" aria-live="polite">
    <div id="status-bar">
      <div id="status-dot" class="busy"></div>
      <span id="status-text">인터뷰 상태를 불러오는 중...</span>
    </div>
    <section id="error-card" class="error-card" hidden>
      <strong>인터뷰 처리 중 오류가 발생했습니다.</strong>
      <p id="error-message"></p>
      <div class="error-actions">
        <button id="retry-btn" class="ghost" type="button" onclick="retryCurrentAction()">다시 시도</button>
      </div>
    </section>
    <div id="turn-history"></div>
    <div id="question-area"></div>
    <div id="mode-prompt" class="prompt-box"></div>
    <label for="answer-input">답변</label>
    <textarea id="answer-input" placeholder="현재 질문에 대한 답변을 입력하세요."></textarea>
    <div class="audio-row">
      <input id="audio-input" type="file" accept="audio/*">
      <button id="transcribe-btn" class="ghost" type="button" onclick="transcribeAudio()">오디오 전사</button>
    </div>
    <div class="controls">
      <button id="submit-btn" type="button" onclick="submitTypedAnswer()">답변 제출</button>
      <button id="skip-btn" class="secondary" type="button" onclick="skipCurrentStep()">현재 질문 건너뛰기</button>
      <button id="end-btn" class="danger" type="button" onclick="endInterview()">인터뷰 종료</button>
    </div>
  </section>
</main>
<div id="report-view"></div>
<script>
const parts = location.pathname.split('/');
const EVAL_ID = parts[2];
const SESSION_ID = parts[3];
const API_BASE = `/api/project-evaluations/${EVAL_ID}/sessions/${SESSION_ID}/interview`;
let mode = 'answer';
let draftAnswer = '';
let followUpQuestion = '';
let followUpReason = '';
let currentQuestion = null;
let currentQuestionIndex = 0;
let totalQuestions = 0;
let retryAction = null;

function hideError() {
  document.getElementById('error-card').hidden = true;
  document.getElementById('error-message').textContent = '';
}

function showError(message, retry = null) {
  document.getElementById('error-card').hidden = false;
  document.getElementById('error-message').textContent = message;
  retryAction = retry;
  document.getElementById('retry-btn').disabled = !retry;
}

function retryCurrentAction() {
  if (retryAction) retryAction();
}

function setStatus(state, text) {
  document.getElementById('status-dot').className = state;
  document.getElementById('status-text').textContent = text;
  if (state !== 'error') hideError();
}

function esc(value) {
  return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, { credentials: 'same-origin', ...options });
  const contentType = response.headers.get('content-type') || '';
  const body = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = body && body.detail ? body.detail : body;
    const message = typeof detail === 'object' ? detail.message || JSON.stringify(detail) : String(detail);
    throw new Error(message || `요청 실패 (${response.status})`);
  }
  return body;
}

async function loadState() {
  setStatus('busy', '인터뷰 상태를 불러오는 중...');
  try {
    const state = await fetchJson(`${API_BASE}/state`);
    renderTurns(state.turns || []);
    if (state.is_completed) {
      currentQuestion = null;
      await completeInterview();
      return;
    }
    if (!state.question) {
      currentQuestion = null;
      setStatus('ready', '인터뷰가 완료되었거나 답변할 질문이 없습니다.');
      disableInputs(true);
      return;
    }
    currentQuestion = state.question;
    currentQuestionIndex = state.current_question_index;
    totalQuestions = state.total_questions;
    mode = 'answer';
    draftAnswer = '';
    followUpQuestion = '';
    followUpReason = '';
    renderQuestion(currentQuestionIndex, totalQuestions, state.question);
    renderModePrompt('현재 질문에 답변해 주세요.');
    setStatus('ready', '답변 입력 대기 중');
  } catch (error) {
    setStatus('error', error.message);
    showError(error.message, loadState);
  }
}

function renderTurns(turns) {
  const history = document.getElementById('turn-history');
  if (!turns.length) {
    history.innerHTML = '';
    return;
  }
  history.innerHTML = turns.map((turn, index) => `
    <article class="turn">
      <strong>완료된 질문 ${index + 1}. ${esc(turn.question_text)}</strong>
      <p>${esc(turn.answer_text)}</p>
    </article>
  `).join('');
}

function renderQuestion(index, total, question) {
  document.getElementById('question-area').innerHTML = `
    <div class="progress">질문 ${index + 1} / ${total}</div>
    <article class="question-card">
      <h2>${esc(question.question)}</h2>
      <div class="question-meta">Bloom: ${esc(question.bloom_level)} · 의도: ${esc(question.intent)}</div>
    </article>
  `;
}

function renderModePrompt(text) {
  const prompt = document.getElementById('mode-prompt');
  prompt.textContent = text;
  prompt.style.display = text ? 'block' : 'none';
}

function disableInputs(disabled) {
  ['answer-input', 'audio-input', 'transcribe-btn', 'submit-btn', 'skip-btn', 'end-btn'].forEach((id) => {
    document.getElementById(id).disabled = disabled;
  });
}

async function submitTypedAnswer() {
  const answer = document.getElementById('answer-input').value.trim();
  if (!answer) {
    setStatus('error', '답변을 입력하세요.');
    return;
  }
  await submitAnswer(answer);
}

async function skipCurrentStep() {
  await submitAnswer(mode === 'follow_up' ? '그 부분은 넘어가겠습니다.' : '이 질문은 넘어가겠습니다.');
}

async function endInterview() {
  await submitAnswer('이제 인터뷰를 끝내겠습니다.', 'end');
}

async function submitAnswer(answerText, modeOverride = null) {
  if (!currentQuestion) return;
  disableInputs(true);
  setStatus('busy', '답변을 처리하는 중...');
  try {
    const response = await fetchJson(`${API_BASE}/answer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode: modeOverride || mode,
        answer_text: answerText,
        draft_answer: draftAnswer,
        follow_up_question: followUpQuestion,
        follow_up_reason: followUpReason,
        current_question_id: currentQuestion.id,
      }),
    });
    handleTurnResponse(response);
  } catch (error) {
    setStatus('error', error.message);
    showError(error.message, () => submitAnswer(answerText, modeOverride));
  } finally {
    if (document.getElementById('report-view').style.display !== 'flex') disableInputs(false);
  }
}

function handleTurnResponse(response) {
  if (response.status === 'need_follow_up') {
    mode = 'follow_up';
    draftAnswer = response.draft_answer || '';
    followUpQuestion = response.follow_up_question || '';
    followUpReason = response.follow_up_reason || '';
    document.getElementById('answer-input').value = '';
    renderModePrompt(`꼬리질문: ${followUpQuestion}`);
    setStatus('ready', '꼬리질문 답변 대기 중');
    return;
  }
  if (response.status === 'need_more') {
    mode = 'more';
    draftAnswer = response.draft_answer || '';
    followUpQuestion = '';
    followUpReason = '';
    document.getElementById('answer-input').value = '';
    renderModePrompt(response.message || '추가로 말씀하실 내용이 있으실까요?');
    setStatus('ready', '추가 답변 대기 중');
    return;
  }
  if (response.status === 'completed') {
    renderReport(response.report);
    return;
  }
  if (response.turn) appendTurn(response.turn);
  mode = 'answer';
  draftAnswer = '';
  followUpQuestion = '';
  followUpReason = '';
  document.getElementById('answer-input').value = '';
  if (response.next_question) {
    currentQuestion = response.next_question;
    currentQuestionIndex = response.next_question.order_index;
    renderQuestion(currentQuestionIndex, totalQuestions, response.next_question);
    renderModePrompt('다음 질문에 답변해 주세요.');
    setStatus('ready', '다음 답변 입력 대기 중');
    loadState();
    return;
  }
  currentQuestion = null;
  completeInterview();
}

function appendTurn(turn) {
  const history = document.getElementById('turn-history');
  history.insertAdjacentHTML('beforeend', `
    <article class="turn">
      <strong>${esc(turn.question_text)}</strong>
      <p>${esc(turn.answer_text)}</p>
    </article>
  `);
}

async function completeInterview() {
  disableInputs(true);
  setStatus('busy', '최종 리포트를 생성하는 중...');
  try {
    const report = await fetchJson(`${API_BASE}/complete`, { method: 'POST' });
    renderReport(report);
  } catch (error) {
    setStatus('error', error.message);
    showError(error.message, completeInterview);
    disableInputs(false);
  }
}

async function transcribeAudio() {
  const input = document.getElementById('audio-input');
  if (!input.files || !input.files[0]) {
    setStatus('error', '전사할 오디오 파일을 선택하세요.');
    showError('전사할 오디오 파일을 선택하세요.');
    return;
  }
  disableInputs(true);
  setStatus('busy', '오디오를 전사하는 중...');
  try {
    const form = new FormData();
    form.append('mode', mode);
    form.append('audio', input.files[0]);
    const result = await fetchJson(`${API_BASE}/transcribe`, { method: 'POST', body: form });
    const textarea = document.getElementById('answer-input');
    textarea.value = [textarea.value.trim(), result.transcript].filter(Boolean).join('\n');
    setStatus('ready', '전사 결과를 답변에 추가했습니다.');
  } catch (error) {
    setStatus('error', error.message);
    showError(error.message, transcribeAudio);
  } finally {
    disableInputs(false);
  }
}

function vClass(value) {
  if (value === '검증 통과') return 'pass';
  if (value === '신뢰 낮음') return 'fail';
  return 'caution';
}

function listHtml(items) {
  if (!items || !items.length) return '<p>없음</p>';
  return `<ul>${items.map((item) => `<li>${esc(item)}</li>`).join('')}</ul>`;
}

function renderReport(report) {
  disableInputs(true);
  document.getElementById('main').style.display = 'none';
  const reportView = document.getElementById('report-view');
  if (!report) {
    reportView.innerHTML = '<section class="section"><h3>리포트 없음</h3><p>리포트 응답을 받지 못했습니다.</p></section>';
  } else {
    const verdictClass = vClass(report.final_decision);
    reportView.innerHTML = `
      <section class="report-header">
        <div class="verdict ${verdictClass}">${esc(report.final_decision)}</div>
        <div class="score-badge">신뢰도 점수: ${esc(Number(report.authenticity_score).toFixed(1))}</div>
      </section>
      <section class="section"><h3>인터뷰 요약</h3><p>${esc(report.summary || '')}</p></section>
      <div class="grid2">
        <section class="section"><h3>강점</h3>${listHtml(report.strengths)}</section>
        <section class="section"><h3>의심 지점</h3>${listHtml(report.suspicious_points)}</section>
        <section class="section"><h3>근거 일치</h3>${listHtml(report.evidence_alignment)}</section>
        <section class="section"><h3>추가 확인 질문</h3>${listHtml(report.recommended_followups)}</section>
      </div>
    `;
  }
  reportView.style.display = 'flex';
  reportView.scrollIntoView({ behavior: 'smooth' });
}

loadState();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


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

    response = RedirectResponse(f"/interview/{evaluation_id}/{session_id}", status_code=303)
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
async def get_interview_page(evaluation_id: str, session_id: str) -> str:
    return _HTML

