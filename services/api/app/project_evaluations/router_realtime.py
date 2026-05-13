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
  if (!confirm('인터뷰를 종료하시겠습니까? 남은 질문은 미응답으로 처리되고, 지금까지의 답변으로 리포트가 작성됩니다.')) {
    return;
  }
  showError('');
  const endBtn = document.getElementById('end-btn');
  endBtn.disabled = true;
  try {
    const report = await api('POST', '/abort', undefined);
    renderReport(report);
  } catch (err) {
    endBtn.disabled = false;
    showError(err.message);
  }
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
<title>음성 인터뷰 (Push-to-Talk)</title>
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
.status-dot.speaking { background: #34d399; animation: pulse .8s infinite; }
.status-dot.recording { background: #f87171; animation: pulse .5s infinite; }
.status-dot.transcribing { background: #a78bfa; animation: pulse 1s infinite; }
.status-dot.reviewing { background: #fbbf24; }
.status-dot.submitting { background: #a78bfa; animation: pulse 1s infinite; }
.status-dot.error { background: #ef4444; }
.status-text { font-size: .9rem; color: #94a3b8; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .4; } }
.question-card { background: #1e293b; border-radius: 12px; padding: 20px; }
.question-card .label { font-size: .75rem; font-weight: 600; color: #7dd3fc; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 8px; }
.question-card .text { font-size: 1.05rem; line-height: 1.55; color: #e2e8f0; white-space: pre-wrap; }
.follow-up-card { background: #2d1f69; border-radius: 12px; padding: 16px 20px; display: none; }
.follow-up-card.show { display: block; }
.follow-up-card .label { font-size: .75rem; font-weight: 600; color: #c4b5fd; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 6px; }
.follow-up-card .text { font-size: .95rem; line-height: 1.55; color: #ede9fe; white-space: pre-wrap; }
.info-card { background: #14532d; border-radius: 12px; padding: 12px 16px; color: #d1fae5; font-size: .88rem; line-height: 1.55; display: none; }
.info-card.show { display: block; }
.draft { padding: 10px 14px; background: #0f172a; border: 1px dashed #334155; border-radius: 8px; font-size: .85rem; color: #94a3b8; white-space: pre-wrap; min-height: 1.4rem; display: none; }
.draft.show { display: block; }
.transcript-area { display: flex; flex-direction: column; gap: 8px; }
.transcript-area label { font-size: .8rem; color: #94a3b8; font-weight: 600; }
textarea { width: 100%; min-height: 110px; resize: vertical; padding: 12px 14px; border-radius: 10px; border: 1px solid #334155; background: #0f172a; color: #e2e8f0; font-size: .95rem; font-family: inherit; line-height: 1.5; }
textarea:focus { outline: none; border-color: #7dd3fc; box-shadow: 0 0 0 2px rgba(125,211,252,.25); }
.actions { display: flex; gap: 10px; justify-content: space-between; flex-wrap: wrap; align-items: center; }
.actions .left, .actions .right { display: flex; gap: 10px; flex-wrap: wrap; }
button { padding: 10px 18px; border: none; border-radius: 8px; font-size: .9rem; font-weight: 600; cursor: pointer; transition: background .15s, opacity .15s; }
button.primary { background: #2563eb; color: #fff; }
button.primary:hover { background: #1d4ed8; }
button.record { background: #16a34a; color: #fff; }
button.record:hover { background: #15803d; }
button.record.recording { background: #dc2626; }
button.record.recording:hover { background: #b91c1c; }
button.ghost { background: transparent; color: #94a3b8; border: 1px solid #334155; }
button.ghost:hover { color: #e2e8f0; border-color: #7dd3fc; }
button.danger { background: #dc2626; color: #fff; }
button.danger:hover { background: #b91c1c; }
button:disabled { opacity: .45; cursor: default; }
.error { padding: 10px 14px; background: #450a0a; border-radius: 8px; color: #fca5a5; font-size: .85rem; display: none; }
.error.show { display: block; }
.notice { font-size: .82rem; color: #94a3b8; }
.notice a { color: #7dd3fc; }
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
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media(max-width: 600px) { .grid2 { grid-template-columns: 1fr; } }
audio { display: none; }
</style>
</head>
<body>
<h1>음성 인터뷰</h1>
<p class="subtitle">버튼을 눌러 녹음하고, 전사 결과를 확인한 뒤 제출하세요. 텍스트로 진행하려면 <a class="notice" id="staged-link" href="#">단계형 화면</a>으로 이동할 수 있습니다.</p>

<div id="main">
  <div class="progress" id="progress">
    <div class="progress-dots" id="progress-dots"></div>
    <span class="progress-summary" id="progress-summary">세션 상태를 불러오는 중입니다...</span>
  </div>
  <div class="status-bar">
    <div class="status-dot idle" id="status-dot"></div>
    <span class="status-text" id="status-text">대기 중</span>
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
  <div class="draft" id="draft"></div>

  <div class="actions">
    <div class="left">
      <button type="button" class="ghost" id="replay-btn" disabled>문제 다시 듣기</button>
    </div>
    <div class="right">
      <button type="button" class="record" id="record-btn" disabled>녹음 시작</button>
    </div>
  </div>

  <div class="transcript-area">
    <label for="answer">전사 결과 (직접 수정해도 됩니다)</label>
    <textarea id="answer" placeholder="여기에 전사된 답변이 표시됩니다. 필요 시 직접 수정한 뒤 '확정 제출'을 눌러주세요."></textarea>
    <div class="actions">
      <div class="left">
        <button type="button" class="danger" id="end-btn">인터뷰 종료</button>
        <button type="button" class="ghost" id="skip-btn">이 문제 건너뛰기</button>
      </div>
      <div class="right">
        <button type="button" class="ghost" id="rerecord-btn" disabled>다시 녹음</button>
        <button type="button" class="primary" id="submit-btn" disabled>확정 제출</button>
      </div>
    </div>
  </div>

  <audio id="tts-audio" preload="auto"></audio>
</div>

<div id="report-view"></div>

<script>
const parts = location.pathname.split('/');
const EVAL_ID = parts[2];
const SESSION_ID = parts[3];
const API_BASE = `/api/project-evaluations/${EVAL_ID}/sessions/${SESSION_ID}/interview`;
const STAGED_URL = `/interview/${EVAL_ID}/${SESSION_ID}`;
document.getElementById('staged-link').href = STAGED_URL;

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

let mediaRecorder = null;
let recorderStream = null;
let recordedChunks = [];
let recorderMime = '';
let isRecording = false;

const ttsAudio = document.getElementById('tts-audio');

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function renderProgress(currentIndex, total) {
  const dots = document.getElementById('progress-dots');
  const summary = document.getElementById('progress-summary');
  if (!dots || !summary) return;
  if (!total || total <= 0) {
    dots.innerHTML = '';
    summary.textContent = '세션 상태를 불러오는 중입니다...';
    return;
  }
  const desiredChildren = total + Math.max(0, total - 1);
  if (dots.childElementCount !== desiredChildren) {
    dots.innerHTML = '';
    for (let i = 0; i < total; i += 1) {
      const dot = document.createElement('span');
      dot.className = 'dot pending';
      dot.dataset.idx = String(i);
      dots.appendChild(dot);
      if (i < total - 1) {
        const dash = document.createElement('span');
        dash.className = 'dash';
        dash.textContent = '-';
        dots.appendChild(dash);
      }
    }
  }
  const nodes = dots.querySelectorAll('.dot');
  nodes.forEach((node, i) => {
    let cls = 'dot pending';
    if (i < currentIndex) cls = 'dot done';
    else if (i === currentIndex) cls = 'dot current';
    node.className = cls;
  });
  const safeIndex = Math.max(0, Math.min(currentIndex, total - 1));
  summary.textContent = `질문 ${safeIndex + 1} / ${total}`;
}

function setStatus(kind, text) {
  document.getElementById('status-dot').className = 'status-dot ' + kind;
  document.getElementById('status-text').textContent = text;
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

function renderQuestion(text, index, total) {
  const card = document.getElementById('question-card');
  if (!text) {
    card.style.display = 'none';
    return;
  }
  card.style.display = 'block';
  document.getElementById('question-label').textContent = `질문 ${index + 1} / ${total}`;
  document.getElementById('question-text').textContent = text;
}

function renderFollowUp(text) {
  const card = document.getElementById('follow-up-card');
  if (!text) {
    card.classList.remove('show');
    document.getElementById('follow-up-text').textContent = '';
    return;
  }
  card.classList.add('show');
  document.getElementById('follow-up-text').textContent = text;
}

function renderDraft(text) {
  const node = document.getElementById('draft');
  if (!text) {
    node.classList.remove('show');
    node.textContent = '';
    return;
  }
  node.classList.add('show');
  node.textContent = `누적 답변: ${text}`;
}

function setButtons(opts) {
  document.getElementById('record-btn').disabled = !opts.canRecord;
  document.getElementById('rerecord-btn').disabled = !opts.canRerecord;
  document.getElementById('submit-btn').disabled = !opts.canSubmit;
  document.getElementById('replay-btn').disabled = !opts.canReplay;
  document.getElementById('skip-btn').disabled = !opts.canSkip;
  document.getElementById('end-btn').disabled = !opts.canEnd;
  const recordBtn = document.getElementById('record-btn');
  if (isRecording) {
    recordBtn.classList.add('recording');
    recordBtn.textContent = '녹음 종료';
  } else {
    recordBtn.classList.remove('recording');
    recordBtn.textContent = '녹음 시작';
  }
}

function syncSubmitFromText() {
  const submitBtn = document.getElementById('submit-btn');
  if (!submitBtn) return;
  const answer = document.getElementById('answer');
  if (!answer) return;
  if (answer.value && answer.value.trim().length > 0) {
    submitBtn.disabled = false;
  }
}

function disableAllButtons() {
  setButtons({ canRecord: false, canRerecord: false, canSubmit: false, canReplay: false, canSkip: false, canEnd: false });
}

function readyForRecording() {
  setStatus('idle', '녹음 준비 완료. 버튼을 눌러 답변을 시작하세요.');
  setButtons({ canRecord: true, canRerecord: false, canSubmit: false, canReplay: true, canSkip: true, canEnd: true });
}

function readyForReview() {
  setStatus('reviewing', '전사 결과를 검토한 뒤 제출하세요.');
  setButtons({ canRecord: false, canRerecord: true, canSubmit: true, canReplay: true, canSkip: true, canEnd: true });
}

async function apiJson(method, path, body) {
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

const FOLLOW_UP_FALLBACK_TEXT = '꼬리질문에 답변해 주세요.';

const ttsCache = new Map();
const ttsInFlight = new Map();

function ttsCacheKey(text) {
  return String(text || '');
}

async function fetchTtsBlobNetwork(text) {
  const res = await fetch(`${API_BASE}/tts`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
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
    throw new Error(detail || `TTS HTTP ${res.status}`);
  }
  return res.blob();
}

function fetchTtsBlob(text) {
  const key = ttsCacheKey(text);
  if (ttsCache.has(key)) {
    return Promise.resolve(ttsCache.get(key));
  }
  if (ttsInFlight.has(key)) {
    return ttsInFlight.get(key);
  }
  const promise = (async () => {
    try {
      const blob = await fetchTtsBlobNetwork(text);
      ttsCache.set(key, blob);
      return blob;
    } finally {
      ttsInFlight.delete(key);
    }
  })();
  ttsInFlight.set(key, promise);
  return promise;
}

function prefetchTts(text) {
  if (!text) {
    return;
  }
  const key = ttsCacheKey(text);
  if (ttsCache.has(key) || ttsInFlight.has(key)) {
    return;
  }
  fetchTtsBlob(text).catch(() => {
    // Prefetch failures stay silent; the real playTts call will surface them.
  });
}

let currentTtsResolve = null;

function stopTtsPlayback() {
  try {
    ttsAudio.pause();
  } catch (_e) {
    /* noop */
  }
  if (ttsAudio.src) {
    try {
      URL.revokeObjectURL(ttsAudio.src);
    } catch (_e) {
      /* noop */
    }
    ttsAudio.removeAttribute('src');
    try {
      ttsAudio.load();
    } catch (_e) {
      /* noop */
    }
  }
  if (currentTtsResolve) {
    const resolve = currentTtsResolve;
    currentTtsResolve = null;
    resolve();
  }
}

async function playTts(text) {
  if (!text) {
    return;
  }
  setStatus('speaking', '인터뷰어가 말하는 중...');
  setButtons({ canRecord: true, canRerecord: false, canSubmit: false, canReplay: false, canSkip: false, canEnd: true });
  syncSubmitFromText();
  const tStart = performance.now();
  const cacheHit = ttsCache.has(ttsCacheKey(text));
  try {
    const blob = await fetchTtsBlob(text);
    const tBlob = performance.now();
    const url = URL.createObjectURL(blob);
    if (ttsAudio.src) {
      URL.revokeObjectURL(ttsAudio.src);
    }
    ttsAudio.src = url;
    await new Promise((resolve, reject) => {
      // 외부에서 stopTtsPlayback()이 호출되면 currentTtsResolve를 통해 직접 resolve된다.
      // 'pause' 이벤트는 src 교체 시 자연 발화될 수 있어 사용하지 않는다.
      currentTtsResolve = resolve;
      const onEnded = () => { cleanup(); currentTtsResolve = null; resolve(); };
      const onError = () => { cleanup(); currentTtsResolve = null; reject(new Error('TTS 오디오 재생 오류')); };
      function cleanup() {
        ttsAudio.removeEventListener('ended', onEnded);
        ttsAudio.removeEventListener('error', onError);
      }
      ttsAudio.addEventListener('ended', onEnded);
      ttsAudio.addEventListener('error', onError);
      ttsAudio.play().then(() => {
        const tPlay = performance.now();
        console.debug(`[tts] blob=${(tBlob - tStart).toFixed(0)}ms play=${(tPlay - tStart).toFixed(0)}ms cache=${cacheHit}`);
      }).catch((err) => {
        cleanup();
        currentTtsResolve = null;
        reject(err);
      });
    });
  } catch (err) {
    showError('TTS 재생 실패: ' + (err.message || err));
  }
}

function pickRecorderMime() {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
    'audio/ogg;codecs=opus',
    'audio/ogg',
  ];
  if (typeof MediaRecorder === 'undefined' || !MediaRecorder.isTypeSupported) {
    return '';
  }
  for (const mime of candidates) {
    if (MediaRecorder.isTypeSupported(mime)) {
      return mime;
    }
  }
  return '';
}

function mimeToExtension(mime) {
  if (!mime) return 'webm';
  if (mime.startsWith('audio/webm')) return 'webm';
  if (mime.startsWith('audio/mp4')) return 'm4a';
  if (mime.startsWith('audio/ogg')) return 'ogg';
  if (mime.startsWith('audio/wav')) return 'wav';
  return 'webm';
}

async function ensureMicStream() {
  if (recorderStream) {
    return recorderStream;
  }
  recorderStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      noiseSuppression: true,
      echoCancellation: true,
      autoGainControl: true,
    },
  });
  return recorderStream;
}

async function startRecording() {
  showError('');
  try {
    const stream = await ensureMicStream();
    recorderMime = pickRecorderMime();
    const recorderOpts = recorderMime ? { mimeType: recorderMime } : undefined;
    mediaRecorder = new MediaRecorder(stream, recorderOpts);
    recordedChunks = [];
    mediaRecorder.addEventListener('dataavailable', (event) => {
      if (event.data && event.data.size > 0) {
        recordedChunks.push(event.data);
      }
    });
    mediaRecorder.addEventListener('stop', onRecorderStop);
    mediaRecorder.start();
    isRecording = true;
    setStatus('recording', '녹음 중... 답변을 마치면 "녹음 종료"를 누르세요.');
    setButtons({ canRecord: true, canRerecord: false, canSubmit: false, canReplay: false, canSkip: false, canEnd: true });
  } catch (err) {
    isRecording = false;
    showError('마이크 권한 또는 초기화 실패: ' + (err.message || err));
    setStatus('error', '마이크 사용 불가. 권한을 확인하거나 단계형 화면을 이용하세요.');
    setButtons({ canRecord: true, canRerecord: false, canSubmit: false, canReplay: true, canSkip: true, canEnd: true });
  }
}

function stopRecording() {
  if (!mediaRecorder || mediaRecorder.state === 'inactive') {
    isRecording = false;
    return;
  }
  setStatus('transcribing', '녹음 처리 중...');
  disableAllButtons();
  try {
    mediaRecorder.stop();
  } catch (_e) {
    /* noop */
  }
}

async function onRecorderStop() {
  isRecording = false;
  const blob = new Blob(recordedChunks, { type: recorderMime || 'audio/webm' });
  recordedChunks = [];
  if (blob.size === 0) {
    showError('녹음 데이터가 비어 있습니다. 다시 녹음해 주세요.');
    readyForRecording();
    return;
  }
  await uploadAndTranscribe(blob);
}

async function uploadAndTranscribe(blob) {
  setStatus('transcribing', '음성 전사 중...');
  showInfo('');
  try {
    const ext = mimeToExtension(blob.type || recorderMime);
    const filename = `answer.${ext}`;
    const form = new FormData();
    form.append('audio', blob, filename);
    form.append('mode', state.mode);
    const res = await fetch(`${API_BASE}/transcribe`, {
      method: 'POST',
      credentials: 'same-origin',
      body: form,
    });
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
      throw new Error(detail || `STT HTTP ${res.status}`);
    }
    const payload = await res.json();
    const transcript = payload.transcript || '';
    document.getElementById('answer').value = transcript;
    document.getElementById('answer').focus();
    readyForReview();
  } catch (err) {
    showError('음성 전사 실패: ' + (err.message || err));
    setStatus('error', '전사 실패. 다시 녹음하세요.');
    setButtons({ canRecord: true, canRerecord: false, canSubmit: false, canReplay: true, canSkip: true, canEnd: true });
  }
}

async function submitAnswer(textOverride, modeOverride, opts) {
  const options = opts || {};
  const answerText = (textOverride !== undefined ? textOverride : document.getElementById('answer').value).trim();
  if (!answerText && !options.allowEmpty) {
    showError('답변 텍스트가 비어 있습니다.');
    return;
  }
  const mode = modeOverride || state.mode;
  setStatus('submitting', '답변 제출 중...');
  disableAllButtons();
  showError('');
  try {
    const response = await apiJson('POST', '/answer', {
      mode,
      answer_text: answerText,
      draft_answer: state.draftAnswer,
      follow_up_question: state.followUpQuestion,
      follow_up_reason: state.followUpReason,
      current_question_id: state.questionId,
    });
    await applyFlowResponse(response);
  } catch (err) {
    showError('답변 제출 실패: ' + (err.message || err));
    setStatus('error', '제출 실패. 다시 시도하세요.');
    setButtons({ canRecord: true, canRerecord: true, canSubmit: true, canReplay: true, canSkip: true, canEnd: true });
  }
}

async function applyFlowResponse(response) {
  state.draftAnswer = response.draft_answer || '';
  state.followUpQuestion = response.follow_up_question || '';
  state.followUpReason = response.follow_up_reason || '';

  if (response.status === 'need_follow_up') {
    state.mode = 'follow_up';
    renderDraft(state.draftAnswer);
    renderFollowUp(state.followUpQuestion);
    showInfo(response.message || FOLLOW_UP_FALLBACK_TEXT);
    document.getElementById('answer').value = '';
    if (state.followUpQuestion) {
      prefetchTts(state.followUpQuestion);
    }
    await playTts(state.followUpQuestion || FOLLOW_UP_FALLBACK_TEXT);
    readyForRecording();
    return;
  }

  state.draftAnswer = '';
  state.followUpQuestion = '';
  state.followUpReason = '';
  renderDraft('');
  renderFollowUp('');
  document.getElementById('answer').value = '';

  if (response.status === 'turn_submitted') {
    state.mode = 'answer';
    showInfo(response.message || '');
    if (response.next_question) {
      state.questionId = response.next_question.id || null;
      state.questionText = response.next_question.question || '';
      state.currentIndex += 1;
      renderQuestion(state.questionText, state.currentIndex, state.totalQuestions);
      renderProgress(state.currentIndex, state.totalQuestions);
      await playTts(state.questionText);
      readyForRecording();
    } else {
      await refreshState();
    }
    return;
  }

  if (response.status === 'ready_to_complete') {
    showInfo('모든 질문 답변이 저장되었습니다. 리포트를 생성합니다...');
    await finalizeAndRender();
    return;
  }

  if (response.status === 'completed') {
    if (response.report) {
      renderReport(response.report);
    } else {
      await finalizeAndRender();
    }
  }
}

async function finalizeAndRender() {
  setStatus('submitting', '리포트 생성 중...');
  try {
    const report = await apiJson('POST', '/complete', undefined);
    renderReport(report);
  } catch (err) {
    showError('리포트 생성 실패: ' + (err.message || err));
    setStatus('error', '리포트 생성 실패');
  }
}

async function refreshState() {
  showError('');
  try {
    const stateResp = await apiJson('GET', '/state');
    state.totalQuestions = stateResp.total_questions || 0;
    state.currentIndex = stateResp.current_question_index || 0;
    if (stateResp.is_completed) {
      await finalizeAndRender();
      return;
    }
    if (!stateResp.question) {
      await finalizeAndRender();
      return;
    }
    state.questionId = stateResp.question.id || null;
    state.questionText = stateResp.question.question || '';
    state.mode = 'answer';
    state.draftAnswer = '';
    state.followUpQuestion = '';
    state.followUpReason = '';
    renderQuestion(state.questionText, state.currentIndex, state.totalQuestions);
    renderFollowUp('');
    renderDraft('');
    renderProgress(state.currentIndex, state.totalQuestions);
    await playTts(state.questionText);
    readyForRecording();
  } catch (err) {
    showError('세션 상태 조회 실패: ' + (err.message || err));
    setStatus('error', '세션 상태를 가져올 수 없습니다.');
  }
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

function renderReport(report) {
  disableAllButtons();
  document.getElementById('main').style.display = 'none';
  const view = document.getElementById('report-view');
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

  view.innerHTML = html;
  view.style.display = 'flex';
  view.scrollIntoView({ behavior: 'smooth' });
}

document.getElementById('record-btn').addEventListener('click', () => {
  if (isRecording) {
    stopRecording();
    return;
  }
  // 인터뷰어 TTS 재생 중에 학생이 녹음을 시작하면 TTS는 즉시 중단한다.
  if (!ttsAudio.paused) {
    stopTtsPlayback();
  }
  startRecording();
});

document.getElementById('rerecord-btn').addEventListener('click', () => {
  document.getElementById('answer').value = '';
  startRecording();
});

document.getElementById('submit-btn').addEventListener('click', () => {
  submitAnswer();
});

document.getElementById('replay-btn').addEventListener('click', async () => {
  if (state.mode === 'follow_up' && state.followUpQuestion) {
    await playTts(state.followUpQuestion);
  } else if (state.questionText) {
    await playTts(state.questionText);
  }
  readyForRecording();
});

document.getElementById('skip-btn').addEventListener('click', async () => {
  if (!confirm('이 문제를 건너뛰시겠습니까?')) {
    return;
  }
  await submitAnswer('건너뛰겠습니다', state.mode === 'follow_up' ? 'follow_up' : 'answer');
});

document.getElementById('end-btn').addEventListener('click', async () => {
  if (!confirm('인터뷰를 종료하시겠습니까? 남은 질문은 미응답으로 처리되고, 지금까지의 답변으로 리포트가 작성됩니다.')) {
    return;
  }
  if (!ttsAudio.paused) {
    stopTtsPlayback();
  }
  if (isRecording) {
    stopRecording();
  }
  disableAllButtons();
  setStatus('submitting', '리포트를 작성하는 중입니다...');
  showError('');
  try {
    const report = await apiJson('POST', '/abort', undefined);
    renderReport(report);
  } catch (err) {
    showError('인터뷰 종료 실패: ' + (err.message || err));
    setStatus('error', '인터뷰 종료 처리에 실패했습니다.');
    setButtons({ canRecord: false, canRerecord: false, canSubmit: false, canReplay: false, canSkip: false, canEnd: true });
  }
});

window.addEventListener('beforeunload', () => {
  if (recorderStream) {
    recorderStream.getTracks().forEach((track) => track.stop());
  }
});

document.getElementById('answer').addEventListener('input', () => {
  // 학생이 STT 단계 없이 textarea에 직접 답변을 적었을 때도 제출이 가능해야 한다.
  syncSubmitFromText();
});

prefetchTts(FOLLOW_UP_FALLBACK_TEXT);

refreshState();
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
