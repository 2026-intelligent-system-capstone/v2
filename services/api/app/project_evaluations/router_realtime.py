"""학생 인터뷰 진입 라우터.

기본 진입 경로는 단계형(HTTP) 평가 화면이다.
- `/interview/{eval}/{session}/open` — 세션 토큰 입력 → 쿠키 설정 → 단계형 화면으로 redirect
- `/interview/{eval}/{session}` — 단계형 인터뷰 화면 (HTTP API 사용)
- `/interview/{eval}/{session}/voice` — 음성 보조 화면 (선택). 평가 상태머신은
  여전히 HTTP 단계형 core가 권한자다. 음성 transport가 실패해도 단계형 화면에서
  인터뷰를 이어 갈 수 있다.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from services.api.app.project_evaluations.persistence.repository import (
    ProjectEvaluationRepository,
)
from services.api.app.project_evaluations.service import ProjectEvaluationService

router = APIRouter(tags=["realtime-interview"])


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

function _getCookie(name) {
  const v = `; ${document.cookie}`;
  const p = v.split(`; ${name}=`);
  return p.length === 2 ? p.pop().split(';').shift() : '';
}
const _stToken = _getCookie(`interview_session_${SESSION_ID}`);
document.getElementById('voice-link').href = `/interview/${EVAL_ID}/${SESSION_ID}/voice` + (_stToken ? `?token=${encodeURIComponent(_stToken)}` : '');

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
        const report = await api('POST', '/complete', undefined);
        renderReport(report);
      } catch (_e) {
        setProgress('인터뷰가 완료되었습니다.');
      }
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

  if (response.status === 'need_more') {
    currentMode = 'more';
    renderDraft(draftAnswer);
    renderFollowUp('');
    showInfo(response.message || '추가로 말씀하실 내용이 있으시면 입력하세요. 없다면 "없습니다"라고 적어주세요.');
    document.getElementById('answer').value = '';
    document.getElementById('answer').focus();
    return;
  }
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
    if (response.report) {
      renderReport(response.report);
      return;
    }
    finalizeAndRender();
  }
}

async function finalizeAndRender() {
  try {
    const report = await api('POST', '/complete', undefined);
    renderReport(report);
  } catch (err) {
    showError(err.message);
  }
}

function vClass(v) {
  if (v === '검증 통과') return 'pass';
  if (v === '신뢰 낮음') return 'fail';
  return 'caution';
}

function tag(v) {
  return `<span class="tag ${vClass(v)}">${esc(v)}</span>`;
}

function listHtml(arr) {
  if (!arr || !arr.length) return '<p class="muted">없음</p>';
  return '<ul class="bullet">' + arr.map((s) => `<li>${esc(String(s))}</li>`).join('') + '</ul>';
}

function renderReport(report) {
  document.getElementById('main').style.display = 'none';
  const view = document.getElementById('report-view');
  const score = typeof report.authenticity_score === 'number'
    ? report.authenticity_score.toFixed(1)
    : report.authenticity_score;
  const verdictClass = vClass(report.final_decision);
  let html = `<div class="report-header"><div class="verdict ${verdictClass}">${esc(report.final_decision)}</div>`
    + `<div class="score-badge">신뢰도 점수 : ${esc(score)}</div></div>`
    + `<div class="section"><h3>인터뷰 요약</h3><p>${esc(report.summary || '')}</p></div>`;

  if (report.area_analyses && report.area_analyses.length) {
    html += '<div class="section"><h3>프로젝트 영역별 신뢰도</h3>'
      + '<table><thead><tr><th>영역</th><th>판정</th><th>점수</th><th>근거</th></tr></thead><tbody>';
    report.area_analyses.forEach((area) => {
      html += `<tr><td>${esc(area.area_name || '')}</td><td>${tag(area.decision || '')}</td>`
        + `<td>${esc(typeof area.score === 'number' ? area.score.toFixed(1) : area.score)}</td>`
        + `<td style="font-size:.8rem">${esc(area.summary || '')}</td></tr>`;
    });
    html += '</tbody></table></div>';
  }

  if (report.question_evaluations && report.question_evaluations.length) {
    html += '<div class="section"><h3>질문별 평가</h3>'
      + '<table><thead><tr><th>#</th><th>질문</th><th>점수</th><th>Bloom</th></tr></thead><tbody>';
    report.question_evaluations.forEach((q) => {
      html += `<tr><td>${esc(q.order_index != null ? q.order_index + 1 : '')}</td>`
        + `<td style="font-size:.8rem">${esc(q.question || '')}</td>`
        + `<td>${esc(typeof q.score === 'number' ? q.score.toFixed(1) : q.score)}</td>`
        + `<td>${esc(q.bloom_level || '')}</td></tr>`;
    });
    html += '</tbody></table></div>';
  }

  html += `<div class="section"><h3>강점</h3>${listHtml(report.strengths)}</div>`
    + `<div class="section"><h3>의심 지점</h3>${listHtml(report.suspicious_points)}</div>`
    + `<div class="section"><h3>근거 일치</h3>${listHtml(report.evidence_alignment)}</div>`
    + `<div class="section"><h3>추가 확인 질문</h3>${listHtml(report.recommended_followups)}</div>`;

  view.innerHTML = html;
  view.style.display = 'flex';
  view.scrollIntoView({ behavior: 'smooth' });
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
  if (!confirm('인터뷰를 종료하시겠습니까? 남은 질문은 미응답으로 처리됩니다.')) {
    return;
  }
  showError('');
  try {
    const response = await submitAnswer(' ', 'end');
    applyFlowResponse(response);
  } catch (err) {
    showError(err.message);
  }
});

refreshState();
</script>
</body>
</html>
"""


_VOICE_HTML = '''
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>음성 보조 인터뷰</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0f172a; color: #e2e8f0; font-family: 'Segoe UI', system-ui, sans-serif; min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 24px 16px; }
h1 { font-size: 1.4rem; font-weight: 700; color: #7dd3fc; margin-bottom: 4px; }
.subtitle { font-size: .85rem; color: #64748b; margin-bottom: 24px; }
#main { width: 100%; max-width: 800px; display: flex; flex-direction: column; gap: 16px; }
#start-overlay { width: 100%; max-width: 800px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 20px; padding: 60px 24px; background: #1e293b; border-radius: 16px; }
#start-overlay p { font-size: .95rem; color: #94a3b8; text-align: center; line-height: 1.6; }
#start-btn { padding: 14px 40px; background: #2563eb; color: #fff; border: none; border-radius: 10px; font-size: 1.05rem; font-weight: 700; cursor: pointer; transition: background .15s; }
#start-btn:hover { background: #1d4ed8; }
#status-bar { display: flex; align-items: center; gap: 10px; padding: 10px 16px; background: #1e293b; border-radius: 10px; }
#status-dot { width: 12px; height: 12px; border-radius: 50%; background: #64748b; flex-shrink: 0; transition: background .3s; }
#status-dot.connecting { background: #fbbf24; animation: pulse 1s infinite; }
#status-dot.ai-speaking { background: #34d399; animation: pulse .6s infinite; }
#status-dot.user-speaking { background: #f87171; animation: pulse .4s infinite; }
#status-dot.ready { background: #34d399; }
#status-dot.evaluating { background: #a78bfa; animation: pulse 1s infinite; }
#status-dot.error { background: #ef4444; }
#status-text { font-size: .9rem; color: #94a3b8; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .4; } }
#transcript { background: #1e293b; border-radius: 12px; padding: 16px; min-height: 300px; max-height: 450px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }
.msg { display: flex; flex-direction: column; gap: 4px; }
.msg-label { font-size: .75rem; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; }
.msg.ai .msg-label { color: #7dd3fc; }
.msg.user .msg-label { color: #86efac; }
.msg.system .msg-label { color: #a78bfa; }
.msg-text { font-size: .95rem; line-height: 1.6; padding: 10px 14px; border-radius: 8px; }
.msg.ai .msg-text { background: #1a3a5e; color: #e2e8f0; }
.msg.user .msg-text { background: #14532d; color: #e2e8f0; margin-left: 24px; }
.msg.system .msg-text { background: #2d1f69; color: #c4b5fd; font-style: italic; font-size: .85rem; }
#live-caption { display: none; flex-direction: column; gap: 4px; }
#live-caption .msg-label { color: #7dd3fc; font-size: .75rem; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; }
#live-caption-text { font-size: .95rem; line-height: 1.6; padding: 10px 14px; border-radius: 8px; background: #1a3a5e; color: #e2e8f0; min-height: 48px; }
#controls { display: flex; gap: 12px; justify-content: space-between; flex-wrap: wrap; align-items: center; }
#controls .right { display: flex; gap: 12px; }
#end-btn { padding: 10px 24px; background: #dc2626; color: #fff; border: none; border-radius: 8px; font-size: .9rem; font-weight: 600; cursor: pointer; transition: background .2s; }
#end-btn:hover { background: #b91c1c; }
#end-btn:disabled { background: #374151; cursor: default; color: #6b7280; }
#ptt-btn { padding: 14px 32px; background: #16a34a; color: #fff; border: none; border-radius: 10px; font-size: 1rem; font-weight: 700; cursor: pointer; transition: background .15s, transform .1s; display: none; user-select: none; }
#ptt-btn:hover:not(:disabled) { background: #15803d; }
#ptt-btn.recording { background: #dc2626; transform: scale(1.05); }
#ptt-btn:disabled { background: #374151; cursor: default; color: #6b7280; }
.info-bar { padding: 10px 16px; background: #1e3a5f; border-radius: 8px; font-size: .85rem; color: #93c5fd; display: none; }
#report-view { width: 100%; max-width: 800px; display: none; flex-direction: column; gap: 20px; }
.report-header { padding: 24px; background: #1e293b; border-radius: 14px; text-align: center; }
.verdict { font-size: 1.8rem; font-weight: 800; margin-bottom: 8px; }
.verdict.pass { color: #34d399; }
.verdict.caution { color: #fbbf24; }
.verdict.fail { color: #f87171; }
.score-badge { display: inline-block; padding: 4px 16px; border-radius: 20px; font-size: .95rem; font-weight: 600; background: #0f172a; color: #94a3b8; }
.section { background: #1e293b; border-radius: 12px; padding: 20px; }
.section h3 { font-size: 1rem; font-weight: 700; color: #7dd3fc; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid #1e3a5f; }
.section p { font-size: .9rem; line-height: 1.7; color: #cbd5e1; }
table { width: 100%; border-collapse: collapse; font-size: .85rem; }
th { text-align: left; padding: 8px 10px; background: #0f172a; color: #94a3b8; font-weight: 600; }
td { padding: 8px 10px; border-top: 1px solid #1e3a5f; color: #cbd5e1; vertical-align: top; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: .75rem; font-weight: 600; }
.tag.pass { background: #14532d; color: #86efac; }
.tag.caution { background: #451a03; color: #fbbf24; }
.tag.fail { background: #450a0a; color: #f87171; }
ul.bullet { padding-left: 20px; display: flex; flex-direction: column; gap: 6px; }
ul.bullet li { font-size: .88rem; color: #cbd5e1; line-height: 1.5; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media(max-width: 600px) { .grid2 { grid-template-columns: 1fr; } }
.notice { font-size: .82rem; color: #94a3b8; }
.notice a { color: #7dd3fc; }
</style>
</head>
<body>
<h1>음성 보조 인터뷰</h1>
<p class="subtitle">평가 진행과 결정은 텍스트 단계형 core가 담당하고, 이 화면은 음성 입출력 보조 역할입니다. 음성 transport가 실패하면 <a href="#" id="staged-link">단계형 화면</a>에서 그대로 이어 갈 수 있습니다.</p>

<div id="start-overlay">
  <p>마이크 권한이 필요합니다.<br>아래 버튼을 눌러 음성 인터뷰를 시작하세요.</p>
  <button id="start-btn">🎙 음성 인터뷰 시작</button>
</div>

<div id="main" style="display:none">
  <div id="status-bar">
    <div id="status-dot" class="connecting"></div>
    <span id="status-text">실시간 인터뷰를 연결하는 중...</span>
  </div>
  <div id="info-bar" class="info-bar"></div>
  <div id="transcript">
    <div class="msg system"><span class="msg-label">시스템</span><span class="msg-text">연결하는 중입니다. 잠시 기다려 주세요...</span></div>
  </div>
  <div id="live-caption">
    <span class="msg-label">인터뷰어</span>
    <div id="live-caption-text"></div>
  </div>
  <div id="controls">
    <a class="notice" href="#" id="back-link">← 단계형 화면으로 돌아가기</a>
    <div class="right">
      <button id="ptt-btn" disabled>🎤 말하기</button>
      <button id="end-btn" disabled>인터뷰 종료</button>
    </div>
  </div>
</div>

<div id="report-view"></div>

<script>
const parts = location.pathname.split('/');
const EVAL_ID = parts[2];
const SESSION_ID = parts[3];
const STAGED_URL = `/interview/${EVAL_ID}/${SESSION_ID}`;

function _getCookie(name) {
  const v = `; ${document.cookie}`;
  const p = v.split(`; ${name}=`);
  return p.length === 2 ? p.pop().split(';').shift() : '';
}
const _urlToken = new URLSearchParams(location.search).get('token') || '';
const _cookieToken = _getCookie(`interview_session_${SESSION_ID}`);
const _sessionToken = _cookieToken || _urlToken;
const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/project-evaluations/ws/interview/${EVAL_ID}/${SESSION_ID}` + (_sessionToken ? `?token=${encodeURIComponent(_sessionToken)}` : '');
document.getElementById('staged-link').href = STAGED_URL;
document.getElementById('back-link').href = STAGED_URL;

let audioContext = null;
let mediaStream = null;
let mediaSource = null;
let processor = null;
let socket = null;
let isRenderingReport = false;
let captureEnabled = false;
let playheadTime = 0;
let currentAiText = '';
let bootstrapDone = false;

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function setStatus(state, text) {
  document.getElementById('status-dot').className = state;
  document.getElementById('status-text').textContent = text;
}

function showInfo(text) {
  const bar = document.getElementById('info-bar');
  if (!text) {
    bar.style.display = 'none';
    bar.textContent = '';
    return;
  }
  bar.textContent = text;
  bar.style.display = 'block';
}

function addMsg(cls, label, text) {
  const transcript = document.getElementById('transcript');
  if (!bootstrapDone) {
    transcript.innerHTML = '';
    bootstrapDone = true;
  }
  const div = document.createElement('div');
  div.className = 'msg ' + cls;
  div.innerHTML = '<span class="msg-label">' + esc(label) + '</span>'
    + '<span class="msg-text">' + esc(text) + '</span>';
  transcript.appendChild(div);
  transcript.scrollTop = transcript.scrollHeight;
}

function setLiveCaption(text) {
  const container = document.getElementById('live-caption');
  const textEl = document.getElementById('live-caption-text');
  if (!text) {
    currentAiText = '';
    container.style.display = 'none';
    textEl.textContent = '';
    return;
  }
  currentAiText = text;
  container.style.display = 'flex';
  textEl.textContent = text;
}

function finalizeAiCaption() {
  if (!currentAiText) {
    return;
  }
  addMsg('ai', '인터뷰어', currentAiText);
  setLiveCaption('');
}

function vClass(v) {
  if (v === '검증 통과') return 'pass';
  if (v === '신뢰 낮음') return 'fail';
  return 'caution';
}

function tag(v) {
  return '<span class="tag ' + vClass(v) + '">' + esc(v) + '</span>';
}

function listHtml(arr) {
  if (!arr || !arr.length) return '<p style="color:#64748b;font-size:.85rem">없음</p>';
  return '<ul class="bullet">' + arr.map(function(s) {
    return '<li>' + esc(String(s)) + '</li>';
  }).join('') + '</ul>';
}

async function renderReport(report) {
  isRenderingReport = true;
  document.getElementById('end-btn').disabled = true;
  captureEnabled = false;
  document.getElementById('main').style.display = 'none';
  const score = typeof report.authenticity_score === 'number'
    ? report.authenticity_score.toFixed(1)
    : report.authenticity_score;
  const verdictClass = vClass(report.final_decision);

  let html = '<div class="report-header">'
    + '<div class="verdict ' + verdictClass + '">' + esc(report.final_decision) + '</div>'
    + '<div class="score-badge">신뢰도 점수 : ' + esc(score) + '</div>'
    + '</div>'
    + '<div class="section"><h3>인터뷰 요약</h3><p>' + esc(report.summary || '') + '</p></div>';

  if (report.area_analyses && report.area_analyses.length) {
    html += '<div class="section"><h3>프로젝트 영역별 신뢰도</h3>'
      + '<table><thead><tr><th>영역</th><th>판정</th><th>점수</th><th>근거</th></tr></thead><tbody>';
    report.area_analyses.forEach(function(area) {
      html += '<tr><td>' + esc(area.area_name || '') + '</td><td>' + tag(area.decision || '') + '</td>'
        + '<td>' + esc(typeof area.score === 'number' ? area.score.toFixed(1) : area.score) + '</td>'
        + '<td style="font-size:.8rem">' + esc(area.summary || '') + '</td></tr>';
    });
    html += '</tbody></table></div>';
  }

  if (report.question_evaluations && report.question_evaluations.length) {
    html += '<div class="section"><h3>질문별 평가</h3>'
      + '<table><thead><tr><th>#</th><th>질문</th><th>점수</th><th>Bloom</th></tr></thead><tbody>';
    report.question_evaluations.forEach(function(question) {
      html += '<tr><td>' + esc(question.order_index != null ? question.order_index + 1 : '') + '</td>'
        + '<td style="font-size:.8rem">' + esc(question.question || '') + '</td>'
        + '<td>' + esc(typeof question.score === 'number' ? question.score.toFixed(1) : question.score) + '</td>'
        + '<td>' + esc(question.bloom_level || '') + '</td></tr>';
    });
    html += '</tbody></table></div>';
  }

  html += '<div class="grid2">'
    + '<div class="section"><h3>강점</h3>' + listHtml(report.strengths) + '</div>'
    + '<div class="section"><h3>의심 지점</h3>' + listHtml(report.suspicious_points) + '</div>'
    + '<div class="section"><h3>근거 일치</h3>' + listHtml(report.evidence_alignment) + '</div>'
    + '<div class="section"><h3>추가 확인 질문</h3>' + listHtml(report.recommended_followups) + '</div>'
    + '</div>';

  const view = document.getElementById('report-view');
  view.innerHTML = html;
  view.style.display = 'flex';
  view.scrollIntoView({ behavior: 'smooth' });
}

function downsampleBuffer(input, inputRate, outputRate) {
  if (inputRate === outputRate) {
    return input;
  }
  const ratio = inputRate / outputRate;
  const newLength = Math.round(input.length / ratio);
  const result = new Float32Array(newLength);
  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
    let accum = 0;
    let count = 0;
    for (let i = offsetBuffer; i < nextOffsetBuffer && i < input.length; i += 1) {
      accum += input[i];
      count += 1;
    }
    result[offsetResult] = count ? accum / count : 0;
    offsetResult += 1;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
}

function floatTo16BitPCM(input) {
  const buffer = new ArrayBuffer(input.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < input.length; i += 1) {
    let sample = Math.max(-1, Math.min(1, input[i]));
    sample = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
    view.setInt16(i * 2, sample, true);
  }
  return buffer;
}

function int16ToFloat32(arrayBuffer) {
  const view = new DataView(arrayBuffer);
  const float32 = new Float32Array(arrayBuffer.byteLength / 2);
  for (let i = 0; i < float32.length; i += 1) {
    float32[i] = view.getInt16(i * 2, true) / 0x8000;
  }
  return float32;
}

function playPcm16(arrayBuffer) {
  if (!audioContext) {
    return;
  }
  const float32 = int16ToFloat32(arrayBuffer);
  const audioBuffer = audioContext.createBuffer(1, float32.length, 24000);
  audioBuffer.copyToChannel(float32, 0);
  const source = audioContext.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(audioContext.destination);
  const now = audioContext.currentTime;
  playheadTime = Math.max(playheadTime, now + 0.02);
  source.start(playheadTime);
  playheadTime += audioBuffer.duration;
}

async function setupAudio() {
  audioContext = new (window.AudioContext || window.webkitAudioContext)();
  await audioContext.resume();
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      noiseSuppression: true,
      echoCancellation: true,
      autoGainControl: true,
    },
  });
  mediaSource = audioContext.createMediaStreamSource(mediaStream);
  processor = audioContext.createScriptProcessor(4096, 1, 1);
  processor.onaudioprocess = (event) => {
    if (!captureEnabled || !socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }
    const input = event.inputBuffer.getChannelData(0);
    const downsampled = downsampleBuffer(input, audioContext.sampleRate, 24000);
    const pcm = floatTo16BitPCM(downsampled);
    socket.send(pcm);
  };
  mediaSource.connect(processor);
  processor.connect(audioContext.destination);
}

function closeSocket() {
  if (socket && socket.readyState <= WebSocket.OPEN) {
    socket.close();
  }
}

function cleanupAudio() {
  captureEnabled = false;
  closeSocket();
  mediaStream?.getTracks?.().forEach((track) => track.stop());
  processor?.disconnect?.();
  mediaSource?.disconnect?.();
  audioContext?.close?.();
}

function endInterview() {
  if (!socket || socket.readyState !== WebSocket.OPEN || isRenderingReport) {
    return;
  }
  document.getElementById('end-btn').disabled = true;
  setStatus('evaluating', '인터뷰 종료 중...');
  socket.send(JSON.stringify({ type: 'interview.end' }));
}

let pttRecording = false;
function setupPtt() {
  const btn = document.getElementById('ptt-btn');
  function startRecording() {
    if (!socket || socket.readyState !== WebSocket.OPEN || pttRecording) return;
    pttRecording = true;
    captureEnabled = true;
    btn.classList.add('recording');
    btn.textContent = '🔴 녹음 중... (다시 누르면 전송)';
    setStatus('user-speaking', '말씀해 주세요...');
  }
  function stopRecording() {
    if (!pttRecording) return;
    pttRecording = false;
    captureEnabled = false;
    btn.classList.remove('recording');
    btn.textContent = '🎤 말하기';
    btn.disabled = true;
    btn.style.display = 'none';
    setStatus('evaluating', '답변을 처리 중...');
    socket.send(JSON.stringify({ type: 'ptt.commit' }));
  }
  btn.addEventListener('click', () => {
    if (pttRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  });
}

function connectSocket() {
  return new Promise((resolve, reject) => {
    socket = new WebSocket(WS_URL);
    socket.binaryType = 'arraybuffer';

    socket.onopen = () => {
      console.log('[socket] onopen');
      document.getElementById('end-btn').disabled = false;
      setStatus('ready', '실시간 인터뷰 연결 완료');
      resolve();
    };

    socket.onmessage = async (event) => {
      if (typeof event.data !== 'string') {
        console.log('[socket] binary audio', event.data.byteLength, 'bytes');
        playPcm16(event.data);
        return;
      }
      const message = JSON.parse(event.data);
      console.log('[socket] message', message.type);
      if (message.type === 'prompt.queued') {
        captureEnabled = false;
        setLiveCaption(message.text || '');
        setStatus('ai-speaking', '인터뷰어가 말하는 중...');
        return;
      }
      if (message.type === 'response.audio.done') {
        finalizeAiCaption();
        return;
      }
      if (message.type === 'input.open') {
        const mode = message.mode;
        function showPtt() {
          const pttBtn = document.getElementById('ptt-btn');
          pttBtn.style.display = 'block';
          pttBtn.disabled = false;
          if (mode === 'identity') {
            showInfo('🎤 말하기 버튼을 눌러 학번과 이름을 말씀해 주세요.');
            setStatus('ready', '말하기 버튼을 눌러주세요');
          } else if (mode === 'follow_up') {
            showInfo('🎤 말하기 버튼을 눌러 꼬리질문에 답변해 주세요.');
            setStatus('ready', '말하기 버튼을 눌러주세요');
          } else if (mode === 'more') {
            showInfo('🎤 추가로 말씀하실 내용이 있으면 말하기 버튼을 눌러주세요.');
            setStatus('ready', '말하기 버튼을 눌러주세요');
          } else {
            showInfo('🎤 말하기 버튼을 눌러 답변해 주세요.');
            setStatus('ready', '말하기 버튼을 눌러주세요');
          }
        }
        const delay = audioContext && playheadTime > audioContext.currentTime
          ? Math.max(0, (playheadTime - audioContext.currentTime) * 1000) + 300
          : 300;
        setTimeout(showPtt, delay);
        return;
      }
      if (message.type === 'transcript.user') {
        addMsg('user', '지원자', message.text || '');
        return;
      }
      if (message.type === 'vad.speech_started') {
        setStatus('user-speaking', '답변을 듣는 중...');
        return;
      }
      if (message.type === 'vad.speech_stopped') {
        setStatus('evaluating', '답변을 처리 중...');
        return;
      }
      if (message.type === 'info') {
        addMsg('system', '시스템', message.message || '');
        return;
      }
      if (message.type === 'transcription.failed') {
        addMsg('system', '시스템', message.message || '음성 전사에 실패했습니다.');
        setStatus('ready', '다시 말씀해 주세요');
        return;
      }
      if (message.type === 'interview.complete') {
        await renderReport(message.report);
        return;
      }
      if (message.type === 'error') {
        captureEnabled = false;
        addMsg('system', '오류', message.message || '실시간 인터뷰 처리 중 오류가 발생했습니다.');
        setStatus('error', '오류 발생');
        document.getElementById('end-btn').disabled = true;
        return;
      }
    };

    socket.onerror = (e) => {
      console.error('[socket] onerror', e);
      reject(new Error('실시간 인터뷰 WebSocket 연결에 실패했습니다.'));
    };

    socket.onclose = (e) => {
      console.log('[socket] onclose', e.code, e.reason);
      captureEnabled = false;
      if (!isRenderingReport) {
        document.getElementById('end-btn').disabled = true;
      }
    };
  });
}

async function bootstrap() {
  console.log('[bootstrap] start');
  document.getElementById('start-overlay').style.display = 'none';
  document.getElementById('main').style.display = 'flex';
  setStatus('connecting', '실시간 인터뷰를 준비하는 중...');
  document.getElementById('end-btn').addEventListener('click', endInterview);
  setupPtt();
  try {
    console.log('[bootstrap] setupAudio start');
    await setupAudio();
    console.log('[bootstrap] setupAudio done, connectSocket start');
    await connectSocket();
    console.log('[bootstrap] connectSocket done');
    showInfo('마이크가 연결되었습니다. 인터뷰어의 안내를 기다려 주세요.');
  } catch (error) {
    console.error('[bootstrap] error', error);
    cleanupAudio();
    addMsg('system', '오류', error.message || String(error));
    setStatus('error', '음성 보조 시작 실패. 단계형 화면에서 계속 진행하세요.');
    document.getElementById('end-btn').disabled = true;
  }
}

window.addEventListener('beforeunload', () => {
  cleanupAudio();
});

document.getElementById('start-btn').addEventListener('click', bootstrap);
</script>
</body>
</html>
'''

# 외부 import 호환용 (테스트 등이 음성 보조 HTML을 검사할 때 사용한다)
_HTML = _VOICE_HTML


@router.get("/interview/{evaluation_id}/{session_id}/open", response_class=HTMLResponse, response_model=None)
async def open_interview_page(
    request: Request,
    evaluation_id: str,
    session_id: str,
    token: str | None = None,
    mode: str = "voice",
) -> HTMLResponse | RedirectResponse:
    if token:
        settings = request.app.state.settings
        session_factory = request.app.state.session_factory
        client_id = request.client.host if request.client else "local"
        with session_factory() as db_session:
            service = ProjectEvaluationService(
                ProjectEvaluationRepository(db_session),
                settings,
            )
            service.ensure_session(evaluation_id, session_id, token, client_id)
        redirect_path = (
            f"/interview/{evaluation_id}/{session_id}"
            if mode == "text"
            else f"/interview/{evaluation_id}/{session_id}/voice"
        )
        response = RedirectResponse(redirect_path, status_code=303)
        response.set_cookie(
            key=f"interview_session_{session_id}",
            value=token,
            httponly=False,
            samesite="lax",
            max_age=60 * 60 * 2,
            secure=request.url.scheme == "https",
        )
        return response
    return HTMLResponse(
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
        httponly=False,
        samesite="lax",
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
