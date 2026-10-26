"""웹 API 서버

실행:  uvicorn app:app --reload
문서:  http://127.0.0.1:8000/docs   (FastAPI가 자동으로 만들어 주는 API 시험 화면)
화면:  http://127.0.0.1:8000/
"""
import hmac
import os
import threading
import time
from collections import deque

import anthropic
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from agent import ask

# 배포 환경에서는 환경변수로 조정 (공개 시연은 Haiku만 + 접속 코드 + 횟수 제한)
ALLOWED_MODELS = set(os.getenv("ALLOWED_MODELS", "claude-opus-5-5,claude-haiku-5-5").split(","))
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "claude-opus-5-5")
ACCESS_CODE = os.getenv("ACCESS_CODE", "")             # 비어 있으면 접속 코드 검사 안 함 (로컬)
PER_IP_PER_HOUR = int(os.getenv("PER_IP_PER_HOUR", "20"))
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "300"))       # 전체 하루 질문 수 상한 = 비용 상한
PREVIEW_ROWS = 20  # 응답에 담을 SQL 결과 줄 수

app = FastAPI(title="아정당 데이터 질의 에이전트", version="0.1.0")


# ---------- 요청·응답 모양 (pydantic이 자동으로 검사) ----------

class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500, examples=["사은품 지급 지연된 건 몇 건이야?"])
    model: str | None = Field(default=None, examples=["claude-haiku-5-5"])


class SqlRun(BaseModel):
    query: str
    columns: list[str] = []
    rows: list[list] = []      # 앞 20줄만
    row_count: int = 0
    error: str | None = None


class AskResponse(BaseModel):
    answer: str
    sqls: list[SqlRun]
    model: str
    input_tokens: int
    output_tokens: int
    latency_s: float


# ---------- 접속 제한 ----------

_lock = threading.Lock()
_ip_hits: dict[str, deque] = {}
_day = {"date": "", "count": 0}


def client_ip(request: Request):
    # 배포 환경은 프록시 뒤라 원래 주소가 X-Forwarded-For 첫 값에 들어옴 (시연용 수준의 구분)
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def check_limits(ip):
    """IP당 1시간 횟수, 전체 하루 횟수를 넘으면 429 (서버 메모리 기준, 재시작하면 초기화)"""
    now = time.time()
    today = time.strftime("%Y-%m-%d")
    with _lock:
        if _day["date"] != today:
            _day.update(date=today, count=0)
        if _day["count"] >= DAILY_LIMIT:
            raise HTTPException(429, "오늘 시연 한도에 도달했습니다. 내일 다시 시도해 주세요")
        hits = _ip_hits.setdefault(ip, deque())
        while hits and now - hits[0] > 3600:
            hits.popleft()
        if len(hits) >= PER_IP_PER_HOUR:
            raise HTTPException(429, f"1시간에 {PER_IP_PER_HOUR}번까지 질문할 수 있습니다")
        hits.append(now)
        _day["count"] += 1


# ---------- 엔드포인트 ----------

@app.get("/health")
def health():
    """서버가 살아 있는지 확인용 (배포 환경의 상태 점검이 부름)"""
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask_endpoint(req: AskRequest, request: Request, x_access_code: str = Header(default="")):
    if ACCESS_CODE and not hmac.compare_digest(x_access_code, ACCESS_CODE):
        raise HTTPException(401, "접속 코드가 맞지 않습니다")
    model = req.model or DEFAULT_MODEL
    if model not in ALLOWED_MODELS:
        raise HTTPException(400, f"model 은 {sorted(ALLOWED_MODELS)} 중 하나여야 합니다")
    check_limits(client_ip(request))

    start = time.time()
    try:
        out = ask(req.question, model=model, verbose=False)
    except anthropic.RateLimitError:
        raise HTTPException(429, "요청이 많습니다. 잠시 후 다시 시도해 주세요")
    except anthropic.APIError as e:
        raise HTTPException(502, f"AI 호출 실패: {type(e).__name__}")

    sqls = []
    for s in out["sqls"]:
        if "error" in s:
            sqls.append(SqlRun(query=s["query"], error=s["error"]))
        else:
            sqls.append(SqlRun(query=s["query"], columns=s["cols"], row_count=len(s["rows"]),
                               rows=[[str(v) for v in r] for r in s["rows"][:PREVIEW_ROWS]]))
    return AskResponse(
        answer=out["answer"], sqls=sqls, model=out["model"],
        input_tokens=out["usage"]["input_tokens"], output_tokens=out["usage"]["output_tokens"],
        latency_s=round(time.time() - start, 1),
    )


# ---------- 시연용 화면 ----------

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>데이터 질의 에이전트</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 760px; margin: 32px auto; padding: 0 16px; color: #222; }
  textarea { width: 100%; height: 70px; font-size: 15px; padding: 8px; box-sizing: border-box; }
  button { margin-top: 8px; padding: 8px 18px; font-size: 15px; cursor: pointer; }
  #answer { white-space: pre-wrap; background: #f6f6f6; padding: 14px; border-radius: 6px; margin-top: 16px; }
  pre { background: #1e1e1e; color: #ddd; padding: 10px; overflow-x: auto; font-size: 13px; border-radius: 6px; }
  .meta { color: #777; font-size: 13px; margin-top: 8px; }
  .ex { font-size: 13px; color: #555; } .ex a { margin-right: 10px; cursor: pointer; color: #0b63c5; }
</style></head><body>
<h2>데이터 질의 에이전트</h2>
<p class="ex">예시:
  <a>사은품 지급 지연된 건 몇 건이고 총 얼마야?</a>
  <a>통신사별 인터넷 가입 건수</a>
  <a>팀별로 가입률이 가장 높은 상담원</a></p>
<textarea id="q" placeholder="질문을 입력하세요"></textarea>
<div><input id="code" type="password" placeholder="접속 코드" __CODE_HIDDEN__>
<select id="m">__MODEL_OPTIONS__</select>
<button id="go">질문하기</button></div>
<div id="answer" hidden></div><div class="meta" id="meta"></div><div id="sqls"></div>
<script>
const $ = (id) => document.getElementById(id);
try { $('code').value = localStorage.getItem('code') || ''; } catch (e) {}
document.querySelectorAll('.ex a').forEach(a => a.onclick = () => { $('q').value = a.textContent; });
$('go').onclick = async () => {
  const question = $('q').value.trim(); if (!question) return;
  $('go').disabled = true; $('answer').hidden = false; $('answer').textContent = '생각하는 중...';
  $('meta').textContent = ''; $('sqls').innerHTML = '';
  try {
    try { localStorage.setItem('code', $('code').value); } catch (e) {}
    const r = await fetch('/ask', { method: 'POST',
                                    headers: { 'Content-Type': 'application/json', 'X-Access-Code': $('code').value },
                                    body: JSON.stringify({ question, model: $('m').value }) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || r.status);
    $('answer').textContent = d.answer;
    $('meta').textContent = `${d.model} · ${d.latency_s}초 · 토큰 ${d.input_tokens}/${d.output_tokens}`;
    d.sqls.forEach((s, i) => {
      const pre = document.createElement('pre');
      pre.textContent = `-- SQL ${i + 1}${s.error ? ' (오류: ' + s.error + ')' : ' · ' + s.row_count + '줄'}\\n${s.query.trim()}`;
      $('sqls').appendChild(pre);
    });
  } catch (e) { $('answer').textContent = '오류: ' + e.message; }
  $('go').disabled = false;
};
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    labels = {"claude-haiku-5-5": "Haiku (빠름·저렴)", "claude-opus-5-5": "Opus"}
    options = "".join(f'<option value="{m}">{labels.get(m, m)}</option>'
                      for m in ["claude-haiku-5-5", "claude-opus-5-5"] if m in ALLOWED_MODELS)
    return (PAGE.replace("__MODEL_OPTIONS__", options)
                .replace("__CODE_HIDDEN__", "" if ACCESS_CODE else "hidden"))
