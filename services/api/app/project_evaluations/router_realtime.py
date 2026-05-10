"""Realtime voice interview routes — HTML page + WebSocket proxy."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket
from fastapi.responses import HTMLResponse

from services.api.app.project_evaluations.persistence.repository import (
    ProjectEvaluationRepository,
)
from services.api.app.project_evaluations.realtime.proxy import run_realtime_session
from services.api.app.project_evaluations.service import ProjectEvaluationService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime-interview"])

# ---------------------------------------------------------------------------
# HTML interview page
# NOTE: plain string — NOT an f-string.  CSS and JS use literal { } braces.
#       IDs are extracted from window.location.pathname in JS (no substitution).
# ---------------------------------------------------------------------------

_HTML = (
    "<!DOCTYPE html>\n"
    '<html lang="ko">\n'
    "<head>\n"
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    "<title>실시간 음성 인터뷰</title>\n"
    "<style>\n"
    "* { box-sizing: border-box; margin: 0; padding: 0; }\n"
    "body { background: #0f172a; color: #e2e8f0; font-family: 'Segoe UI', system-ui, sans-serif;"
    " min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 24px 16px; }\n"
    "h1 { font-size: 1.4rem; font-weight: 700; color: #7dd3fc; margin-bottom: 4px; }\n"
    ".subtitle { font-size: .85rem; color: #64748b; margin-bottom: 24px; }\n"
    "#main { width: 100%; max-width: 800px; display: flex; flex-direction: column; gap: 16px; }\n"
    "#status-bar { display: flex; align-items: center; gap: 10px; padding: 10px 16px; background: #1e293b; border-radius: 10px; }\n"
    "#status-dot { width: 12px; height: 12px; border-radius: 50%; background: #64748b; flex-shrink: 0; transition: background .3s; }\n"
    "#status-dot.connecting { background: #fbbf24; animation: pulse 1s infinite; }\n"
    "#status-dot.ai-speaking { background: #34d399; animation: pulse .6s infinite; }\n"
    "#status-dot.user-speaking { background: #f87171; animation: pulse .4s infinite; }\n"
    "#status-dot.ready { background: #34d399; }\n"
    "#status-dot.evaluating { background: #a78bfa; animation: pulse 1s infinite; }\n"
    "#status-text { font-size: .9rem; color: #94a3b8; }\n"
    "@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .4; } }\n"
    "#transcript { background: #1e293b; border-radius: 12px; padding: 16px; min-height: 300px;"
    " max-height: 450px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }\n"
    ".msg { display: flex; flex-direction: column; gap: 4px; }\n"
    ".msg-label { font-size: .75rem; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; }\n"
    ".msg.ai .msg-label { color: #7dd3fc; }\n"
    ".msg.user .msg-label { color: #86efac; }\n"
    ".msg.system .msg-label { color: #a78bfa; }\n"
    ".msg-text { font-size: .95rem; line-height: 1.6; padding: 10px 14px; border-radius: 8px; }\n"
    ".msg.ai .msg-text { background: #1a3a5e; color: #e2e8f0; }\n"
    ".msg.user .msg-text { background: #14532d; color: #e2e8f0; margin-left: 24px; }\n"
    ".msg.system .msg-text { background: #2d1f69; color: #c4b5fd; font-style: italic; font-size: .85rem; }\n"
    "#ai-streaming { display: none; flex-direction: column; gap: 4px; }\n"
    "#ai-streaming .msg-label { color: #7dd3fc; font-size: .75rem; font-weight: 600;"
    " text-transform: uppercase; letter-spacing: .05em; }\n"
    "#ai-streaming-text { font-size: .95rem; line-height: 1.6; padding: 10px 14px; border-radius: 8px;"
    " background: #1a3a5e; color: #e2e8f0; min-height: 48px; }\n"
    "#controls { display: flex; gap: 12px; justify-content: flex-end; }\n"
    "#end-btn { padding: 10px 24px; background: #dc2626; color: #fff; border: none; border-radius: 8px;"
    " font-size: .9rem; font-weight: 600; cursor: pointer; transition: background .2s; }\n"
    "#end-btn:hover { background: #b91c1c; }\n"
    "#end-btn:disabled { background: #374151; cursor: default; color: #6b7280; }\n"
    ".info-bar { padding: 10px 16px; background: #1e3a5f; border-radius: 8px; font-size: .85rem;"
    " color: #93c5fd; display: none; }\n"
    "#report-view { width: 100%; max-width: 800px; display: none; flex-direction: column; gap: 20px; }\n"
    ".report-header { padding: 24px; background: #1e293b; border-radius: 14px; text-align: center; }\n"
    ".verdict { font-size: 1.8rem; font-weight: 800; margin-bottom: 8px; }\n"
    ".verdict.pass { color: #34d399; }\n"
    ".verdict.caution { color: #fbbf24; }\n"
    ".verdict.fail { color: #f87171; }\n"
    ".score-badge { display: inline-block; padding: 4px 16px; border-radius: 20px; font-size: .95rem;"
    " font-weight: 600; background: #0f172a; color: #94a3b8; }\n"
    ".section { background: #1e293b; border-radius: 12px; padding: 20px; }\n"
    ".section h3 { font-size: 1rem; font-weight: 700; color: #7dd3fc; margin-bottom: 12px;"
    " padding-bottom: 8px; border-bottom: 1px solid #1e3a5f; }\n"
    ".section p { font-size: .9rem; line-height: 1.7; color: #cbd5e1; }\n"
    "table { width: 100%; border-collapse: collapse; font-size: .85rem; }\n"
    "th { text-align: left; padding: 8px 10px; background: #0f172a; color: #94a3b8; font-weight: 600; }\n"
    "td { padding: 8px 10px; border-top: 1px solid #1e3a5f; color: #cbd5e1; vertical-align: top; }\n"
    ".tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: .75rem; font-weight: 600; }\n"
    ".tag.pass { background: #14532d; color: #86efac; }\n"
    ".tag.caution { background: #451a03; color: #fbbf24; }\n"
    ".tag.fail { background: #450a0a; color: #f87171; }\n"
    "ul.bullet { padding-left: 20px; display: flex; flex-direction: column; gap: 6px; }\n"
    "ul.bullet li { font-size: .88rem; color: #cbd5e1; line-height: 1.5; }\n"
    ".grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }\n"
    "@media(max-width: 600px) { .grid2 { grid-template-columns: 1fr; } }\n"
    "</style>\n"
    "</head>\n"
    "<body>\n"
    "<h1>프로젝트 수행 진위 평가 — 실시간 인터뷰</h1>\n"
    "<p class=\"subtitle\">마이크 권한을 허용하고 인터뷰어의 질문에 음성으로 답변하세요.</p>\n"
    "\n"
    '<div id="main">\n'
    '  <div id="status-bar">\n'
    '    <div id="status-dot" class="connecting"></div>\n'
    '    <span id="status-text">서버에 연결 중...</span>\n'
    "  </div>\n"
    '  <div id="info-bar" class="info-bar"></div>\n'
    '  <div id="transcript">\n'
    '    <div class="msg system"><span class="msg-label">시스템</span>'
    '<span class="msg-text">연결하는 중입니다. 잠시 기다려 주세요...</span></div>\n'
    "  </div>\n"
    '  <div id="ai-streaming">\n'
    '    <span class="msg-label">인터뷰어</span>\n'
    '    <div id="ai-streaming-text"></div>\n'
    "  </div>\n"
    '  <div id="controls">\n'
    '    <button id="end-btn" onclick="endInterview()" disabled>인터뷰 종료</button>\n'
    "  </div>\n"
    "</div>\n"
    "\n"
    '<div id="report-view"></div>\n'
    "\n"
    "<script>\n"
    "// Extract IDs from URL path: /interview/{eval_id}/{session_id}\n"
    "const parts = location.pathname.split('/');\n"
    "const EVAL_ID = parts[2];\n"
    "const SESSION_ID = parts[3];\n"
    "const WS_SCHEME = location.protocol === 'https:' ? 'wss' : 'ws';\n"
    "const WS_URL = WS_SCHEME + '://' + location.host + '/ws/interview/' + EVAL_ID + '/' + SESSION_ID;\n"
    "\n"
    "let ws = null;\n"
    "let audioCtx = null;\n"
    "let nextPlayAt = 0;\n"
    "\n"
    "// ── Audio playback ────────────────────────────────────────────────────────\n"
    "\n"
    "function ensureAudioCtx() {\n"
    "  if (!audioCtx || audioCtx.state === 'closed') {\n"
    "    audioCtx = new AudioContext({ sampleRate: 24000 });\n"
    "    nextPlayAt = 0;\n"
    "  }\n"
    "  if (audioCtx.state === 'suspended') audioCtx.resume();\n"
    "}\n"
    "\n"
    "function playPCM16(arrayBuf) {\n"
    "  ensureAudioCtx();\n"
    "  const i16 = new Int16Array(arrayBuf);\n"
    "  const f32 = new Float32Array(i16.length);\n"
    "  for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768.0;\n"
    "  const ab = audioCtx.createBuffer(1, f32.length, 24000);\n"
    "  ab.getChannelData(0).set(f32);\n"
    "  const src = audioCtx.createBufferSource();\n"
    "  src.buffer = ab;\n"
    "  src.connect(audioCtx.destination);\n"
    "  const now = audioCtx.currentTime;\n"
    "  const start = Math.max(nextPlayAt, now);\n"
    "  src.start(start);\n"
    "  nextPlayAt = start + ab.duration;\n"
    "}\n"
    "\n"
    "// ── Microphone capture ────────────────────────────────────────────────────\n"
    "\n"
    "async function startMic() {\n"
    "  const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });\n"
    "  ensureAudioCtx();\n"
    "  const source = audioCtx.createMediaStreamSource(stream);\n"
    "  const proc = audioCtx.createScriptProcessor(4096, 1, 1);\n"
    "  proc.onaudioprocess = function(e) {\n"
    "    if (!ws || ws.readyState !== WebSocket.OPEN) return;\n"
    "    const f32 = e.inputBuffer.getChannelData(0);\n"
    "    const i16 = new Int16Array(f32.length);\n"
    "    for (let i = 0; i < f32.length; i++) {\n"
    "      i16[i] = Math.max(-32768, Math.min(32767, f32[i] * 32768));\n"
    "    }\n"
    "    ws.send(i16.buffer);\n"
    "  };\n"
    "  source.connect(proc);\n"
    "  proc.connect(audioCtx.destination);\n"
    "}\n"
    "\n"
    "// ── WebSocket ─────────────────────────────────────────────────────────────\n"
    "\n"
    "function connect() {\n"
    "  setStatus('connecting', '서버에 연결 중...');\n"
    "  ws = new WebSocket(WS_URL);\n"
    "  ws.binaryType = 'arraybuffer';\n"
    "\n"
    "  ws.onopen = async function() {\n"
    "    try {\n"
    "      await startMic();\n"
    "      setStatus('ready', '인터뷰어가 첫 번째 질문을 시작합니다...');\n"
    "      document.getElementById('end-btn').disabled = false;\n"
    "      addMsg('system', '시스템', '마이크 연결 완료. 인터뷰어가 질문을 시작합니다.');\n"
    "    } catch(err) {\n"
    "      addMsg('system', '오류', '마이크 접근 실패: ' + err.message);\n"
    "      setStatus('connecting', '마이크 권한이 필요합니다');\n"
    "    }\n"
    "  };\n"
    "\n"
    "  ws.onmessage = function(e) {\n"
    "    if (e.data instanceof ArrayBuffer) {\n"
    "      if (e.data.byteLength > 0) playPCM16(e.data);\n"
    "      return;\n"
    "    }\n"
    "    try { handleMsg(JSON.parse(e.data)); } catch(ex) {}\n"
    "  };\n"
    "\n"
    "  ws.onclose = function(ev) {\n"
    "    setStatus('connecting', '연결 종료 (코드 ' + ev.code + ')');\n"
    "  };\n"
    "\n"
    "  ws.onerror = function() {\n"
    "    addMsg('system', '오류', 'WebSocket 연결 오류가 발생했습니다.');\n"
    "  };\n"
    "}\n"
    "\n"
    "function handleMsg(msg) {\n"
    "  switch (msg.type) {\n"
    "    case 'transcript.ai.delta':\n"
    "      showStreamingAI(msg.text);\n"
    "      setStatus('ai-speaking', '인터뷰어가 말하는 중...');\n"
    "      break;\n"
    "    case 'transcript.ai.done':\n"
    "      finalizeStreamingAI(msg.text);\n"
    "      setStatus('ready', '답변을 말씀해 주세요');\n"
    "      break;\n"
    "    case 'transcript.user':\n"
    "      addMsg('user', '지원자', msg.text);\n"
    "      setStatus('ready', '답변 ' + (msg.turn_index + 1) + '개 수집됨');\n"
    "      break;\n"
    "    case 'vad.speech_started':\n"
    "      setStatus('user-speaking', '녹음 중...');\n"
    "      break;\n"
    "    case 'vad.speech_stopped':\n"
    "      setStatus('ai-speaking', '처리 중...');\n"
    "      break;\n"
    "    case 'info':\n"
    "      showInfo(msg.message);\n"
    "      break;\n"
    "    case 'evaluating':\n"
    "      setStatus('evaluating', msg.message);\n"
    "      document.getElementById('end-btn').disabled = true;\n"
    "      addMsg('system', '시스템', msg.message);\n"
    "      break;\n"
    "    case 'interview.complete':\n"
    "      document.getElementById('main').style.display = 'none';\n"
    "      renderReport(msg.report);\n"
    "      break;\n"
    "    case 'error':\n"
    "      addMsg('system', '오류', msg.message);\n"
    "      setStatus('connecting', '오류 발생');\n"
    "      break;\n"
    "  }\n"
    "}\n"
    "\n"
    "// ── UI helpers ────────────────────────────────────────────────────────────\n"
    "\n"
    "var aiStreamText = '';\n"
    "\n"
    "function showStreamingAI(delta) {\n"
    "  var container = document.getElementById('ai-streaming');\n"
    "  var textEl = document.getElementById('ai-streaming-text');\n"
    "  container.style.display = 'flex';\n"
    "  aiStreamText += delta;\n"
    "  textEl.textContent = aiStreamText;\n"
    "}\n"
    "\n"
    "function finalizeStreamingAI(full) {\n"
    "  document.getElementById('ai-streaming').style.display = 'none';\n"
    "  addMsg('ai', '인터뷰어', full || aiStreamText);\n"
    "  aiStreamText = '';\n"
    "}\n"
    "\n"
    "function addMsg(cls, label, text) {\n"
    "  var t = document.getElementById('transcript');\n"
    "  var div = document.createElement('div');\n"
    "  div.className = 'msg ' + cls;\n"
    "  div.innerHTML = '<span class=\"msg-label\">' + label + '</span>'\n"
    "                + '<span class=\"msg-text\">' + esc(text) + '</span>';\n"
    "  t.appendChild(div);\n"
    "  t.scrollTop = t.scrollHeight;\n"
    "}\n"
    "\n"
    "function setStatus(state, text) {\n"
    "  document.getElementById('status-dot').className = state;\n"
    "  document.getElementById('status-text').textContent = text;\n"
    "}\n"
    "\n"
    "function showInfo(text) {\n"
    "  var bar = document.getElementById('info-bar');\n"
    "  bar.textContent = text;\n"
    "  bar.style.display = 'block';\n"
    "}\n"
    "\n"
    "function esc(s) {\n"
    "  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');\n"
    "}\n"
    "\n"
    "function endInterview() {\n"
    "  if (ws && ws.readyState === WebSocket.OPEN) {\n"
    "    ws.send(JSON.stringify({ type: 'interview.end' }));\n"
    "    document.getElementById('end-btn').disabled = true;\n"
    "    setStatus('evaluating', '인터뷰 종료 중...');\n"
    "  }\n"
    "}\n"
    "\n"
    "// ── Report rendering ──────────────────────────────────────────────────────\n"
    "\n"
    "function vClass(v) {\n"
    "  if (v === '검증 통과') return 'pass';\n"
    "  if (v === '신뢰 낮음') return 'fail';\n"
    "  return 'caution';\n"
    "}\n"
    "\n"
    "function tag(v) {\n"
    "  return '<span class=\"tag ' + vClass(v) + '\">' + esc(v) + '</span>';\n"
    "}\n"
    "\n"
    "function listHtml(arr) {\n"
    "  if (!arr || !arr.length) return '<p style=\"color:#64748b;font-size:.85rem\">없음</p>';\n"
    "  return '<ul class=\"bullet\">' + arr.map(function(s) {\n"
    "    return '<li>' + esc(String(s)) + '</li>';\n"
    "  }).join('') + '</ul>';\n"
    "}\n"
    "\n"
    "function renderReport(r) {\n"
    "  var vc = vClass(r.final_decision);\n"
    "  var score = typeof r.authenticity_score === 'number'\n"
    "    ? r.authenticity_score.toFixed(1) : r.authenticity_score;\n"
    "\n"
    "  var html = '<div class=\"report-header\">'\n"
    "    + '<div class=\"verdict ' + vc + '\">' + esc(r.final_decision) + '</div>'\n"
    "    + '<div class=\"score-badge\">신뢰도 점수 : ' + score + '</div>'\n"
    "    + '</div>'\n"
    "    + '<div class=\"section\"><h3>인터뷰 요약</h3><p>' + esc(r.summary || '') + '</p></div>';\n"
    "\n"
    "  if (r.area_analyses && r.area_analyses.length) {\n"
    "    html += '<div class=\"section\"><h3>프로젝트 영역별 신뢰도</h3>'\n"
    "          + '<table><thead><tr><th>영역</th><th>판정</th><th>점수</th><th>근거</th></tr></thead><tbody>';\n"
    "    r.area_analyses.forEach(function(a) {\n"
    "      html += '<tr><td>' + esc(a.area_name||'') + '</td><td>' + tag(a.decision||'') + '</td>'\n"
    "            + '<td>' + (typeof a.score==='number'?a.score.toFixed(1):a.score) + '</td>'\n"
    "            + '<td style=\"font-size:.8rem\">' + esc(a.summary||'') + '</td></tr>';\n"
    "    });\n"
    "    html += '</tbody></table></div>';\n"
    "  }\n"
    "\n"
    "  if (r.question_evaluations && r.question_evaluations.length) {\n"
    "    html += '<div class=\"section\"><h3>질문별 평가</h3>'\n"
    "          + '<table><thead><tr><th>#</th><th>질문</th><th>점수</th><th>Bloom</th></tr></thead><tbody>';\n"
    "    r.question_evaluations.forEach(function(q) {\n"
    "      html += '<tr><td>' + (q.order_index!=null?q.order_index+1:'') + '</td>'\n"
    "            + '<td style=\"font-size:.8rem\">' + esc(q.question||'') + '</td>'\n"
    "            + '<td>' + (typeof q.score==='number'?q.score.toFixed(1):q.score) + '</td>'\n"
    "            + '<td>' + esc(q.bloom_level||'') + '</td></tr>';\n"
    "    });\n"
    "    html += '</tbody></table></div>';\n"
    "  }\n"
    "\n"
    "  html += '<div class=\"grid2\">'\n"
    "        + '<div class=\"section\"><h3>강점</h3>' + listHtml(r.strengths) + '</div>'\n"
    "        + '<div class=\"section\"><h3>의심 지점</h3>' + listHtml(r.suspicious_points) + '</div>'\n"
    "        + '<div class=\"section\"><h3>근거 일치</h3>' + listHtml(r.evidence_alignment) + '</div>'\n"
    "        + '<div class=\"section\"><h3>추가 확인 질문</h3>' + listHtml(r.recommended_followups) + '</div>'\n"
    "        + '</div>';\n"
    "\n"
    "  var el = document.getElementById('report-view');\n"
    "  el.innerHTML = html;\n"
    "  el.style.display = 'flex';\n"
    "  el.scrollIntoView({ behavior: 'smooth' });\n"
    "}\n"
    "\n"
    "connect();\n"
    "</script>\n"
    "</body>\n"
    "</html>\n"
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/interview/{evaluation_id}/{session_id}", response_class=HTMLResponse)
async def get_interview_page(evaluation_id: str, session_id: str) -> str:
    return _HTML


@router.websocket("/ws/interview/{evaluation_id}/{session_id}")
async def interview_websocket(
    websocket: WebSocket,
    evaluation_id: str,
    session_id: str,
) -> None:
    settings = websocket.app.state.settings
    session_factory = websocket.app.state.session_factory

    with session_factory() as db_session:
        repo = ProjectEvaluationRepository(db_session)
        service = ProjectEvaluationService(repo, settings)

        service.ensure_session(evaluation_id, session_id)
        questions_read = service.list_questions(evaluation_id)
        questions = [
            {
                "id": q.id,
                "question": q.question,
                "intent": q.intent,
                "bloom_level": q.bloom_level,
            }
            for q in questions_read
        ]

        async def on_complete(answer_texts: list[str]) -> dict:
            loop = asyncio.get_event_loop()
            report = await loop.run_in_executor(
                None,
                lambda: service.submit_turns_bulk(
                    evaluation_id, session_id, answer_texts
                ),
            )
            return report.model_dump(mode="json")

        await run_realtime_session(
            browser_ws=websocket,
            api_key=settings.OPENAI_API_KEY,
            questions=questions,
            on_complete=on_complete,
            model=settings.OPENAI_REALTIME_MODEL,
        )
