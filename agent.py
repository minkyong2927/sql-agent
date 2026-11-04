import sys

import anthropic
import duckdb
from dotenv import load_dotenv

from guard import UnsafeSQL, check_sql

load_dotenv()
client = anthropic.Anthropic()

# 안전장치 1: 읽기 전용 + 파일·외부 접근 금지로 DB 열기
con = duckdb.connect("ajd.duckdb", read_only=True, config={"enable_external_access": False})
ALLOWED_TABLES = {r[0] for r in con.execute("SHOW TABLES").fetchall()}

MAX_ROWS = 50  # AI에게 돌려줄 최대 줄 수 (결과가 너무 길면 토큰 낭비)
MAX_STEPS = 8  # SQL 실행 최대 횟수 (무한 반복 방지)


def describe_schema():
    """DB에서 테이블·칸 목록을 읽어 AI에게 줄 설명문을 만듦"""
    lines = []
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    for t in tables:
        cols = con.execute(f"DESCRIBE {t}").fetchall()
        lines.append(f"- {t}(" + ", ".join(f"{c[0]} {c[1]}" for c in cols) + ")")
    return "\n".join(lines)


SYSTEM = f"""당신은 통신·렌탈 가입 중개 회사의 데이터 분석 도우미입니다.
운영자의 질문을 DuckDB SQL로 바꿔 run_sql 도구로 실행하고, 결과를 근거로 한국어로 답합니다.

## 테이블
{describe_schema()}

## 값 규칙
- products.category: '인터넷', '인터넷+TV', '휴대폰', '렌탈'
- consultation_requests.channel: '웹', '앱', '전화', '카카오'
- consultations.result: '가입', '보류', '거절'
- applications.status: '접수', '설치완료', '개통완료', '취소'
- installation_visits.status: '예정', '완료', '지연', '취소'
- gift_payouts.status: '대기', '지급완료', '지연'
- 데이터 기준일은 2026-10-25 입니다. "이번 달", "지난달"은 이 날짜 기준으로 해석합니다.

## 답변 규칙
- 숫자는 반드시 SQL 실행 결과에서 가져옵니다. 추측하지 않습니다.
- 비율(%)·합계·평균·차이 같은 계산도 SQL 안에서 끝냅니다. 답변에 쓰는 숫자는 SQL 결과에 그대로 있는 값이어야 하며, 결과를 보고 직접 나누거나 더하지 않습니다.
- 질문이 애매하면 합리적인 기준을 정해 실행하고, 답변 끝에 그 기준을 한 줄로 밝힙니다.
- SQL 오류가 나면 오류 메시지를 보고 고쳐서 다시 실행합니다.
- 답변은 짧게: 핵심 숫자 먼저, 필요하면 표.

## 사내 문서
- 사내 지표·정책 용어(예: 순가입, 골든타임 응대율, 청약철회, 고액 사은품)는 사내 문서에 정의가 있습니다.
- 질문에 용어가 그대로 나오면 그 문서가 질문 앞 '참고 문서'로 붙어 옵니다. 그 정의를 따르고 답변 끝에 문서 이름을 밝힙니다.
- 참고 문서가 없는데 테이블·칸·값만으로는 기준을 정할 수 없는 사내 표현(지표 이름, "수도권", "디지털 채널", "응대 안 한" 같은 묶음·상태)이 있으면
  SQL을 짜기 전에 search_docs 로 정의를 찾습니다. 테이블·칸·값으로 바로 답할 수 있는 질문에는 검색하지 않습니다.
- 질문이 DB에 있는 값('지연', '취소' 같은 status 값)을 그대로 말하면 문서보다 DB 값이 우선입니다.
  예: "지급이 지연된 사은품"은 gift_payouts.status = '지연' 이지, 문서의 'SLA 위반'이 아닙니다.
"""

TOOLS = [
    {
        "name": "run_sql",
        "description": "DuckDB에 SELECT 쿼리를 실행하고 결과 표를 돌려줍니다. 읽기 전용입니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "실행할 DuckDB SQL (SELECT 문)"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "strict": True,
    }
]

DOC_TOOL = {
    "name": "search_docs",
    "description": "사내 문서(지표 정의서·운영 규칙·사은품 정책)에서 용어 정의를 검색해 관련 조각 3개를 돌려줍니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "찾을 용어나 표현 (예: '수도권', '응대 안 한 신청')"},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    "strict": True,
}


def run_sql(query):
    """SQL을 검사·실행해서 (칸 이름, 줄 목록)을 돌려줌. 오류면 예외가 그대로 올라감"""
    query = check_sql(query, ALLOWED_TABLES)  # 안전장치 2: 실행 전 SQL 검사
    cur = con.cursor()  # 평가 때 여러 질문을 동시에 돌려도 안전하게 질문마다 따로 연결
    cur.execute(query)
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchall()  # LIMIT 200이 붙어 있어 최대 200줄


def to_text(cols, rows):
    """결과를 AI에게 보낼 글자 표로 바꿈"""
    text = " | ".join(cols) + "\n"
    text += "\n".join(" | ".join(str(v) for v in row) for row in rows[:MAX_ROWS])
    if len(rows) > MAX_ROWS:
        text += f"\n... ({MAX_ROWS}줄까지만 표시)"
    return text


def with_knowledge(question, knowledge):
    """사내 문서를 질문 앞에 붙임 → (보낼 글, 붙인 조각 id 목록)
    rag 는 문서 용어(소제목)가 질문에 그대로 나온 조각만 붙임. 비슷하기만 한 조각까지 붙이면
    관계없는 질문의 해석이 흔들려서(기본 문항 10번: 문서 없이 3/3 → 붙이면 0/3) 나머지는 모델이 search_docs 로 찾게 함"""
    if knowledge == "none":
        return question, []
    import rag  # 임베딩 모델이 무거워서 쓸 때만 불러옴
    hits = [h for h in rag.search(question) if h["term"]] if knowledge == "rag" else rag.load_chunks()
    if not hits:
        return question, []
    text = f"## 참고 문서 (사내 지식 검색 결과)\n{rag.to_prompt(hits)}\n\n## 질문\n{question}"
    return text, [h["id"] for h in hits]


def ask(question, model="claude-opus-5-5", verbose=True, cache=True, effort="medium", max_steps=MAX_STEPS,
        knowledge="rag"):
    """질문 하나를 받아 답변·실행한 SQL과 결과·토큰 사용량을 돌려줌
    effort·max_steps: 이 질문에 쓸 실행 예산 (router.py가 난이도에 따라 정함)
    knowledge: 사내 문서를 어떻게 넣을지 (rag: 용어 일치 조각 + search_docs 도구 / full: 전부 / none: 안 넣음)"""
    content, docs = with_knowledge(question, knowledge)
    if verbose and docs:
        print(f"[참고 문서] {docs}")
    messages = [{"role": "user", "content": content}]
    sqls = []  # [{"query", "cols", "rows"} 또는 {"query", "error"}]
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    tools = TOOLS + [DOC_TOOL] if knowledge == "rag" else TOOLS
    out = {"answer": "SQL 실행 횟수 한도를 넘었습니다.", "sqls": sqls, "usage": usage,
           "model": model, "stop_reason": "max_steps", "messages": messages, "docs": docs}

    # 안전 필터에 걸려 거절되면 서버가 다른 모델로 자동 재시도 (Opus만 지원, Haiku는 미지원)
    extra = {}
    if model.startswith("claude-opus"):
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}

    # 프롬프트 캐싱: 도구 정의 + 시스템 프롬프트(스키마)는 모든 질문에서 똑같음
    # → 끝에 표시를 달아 두 번째 요청부터는 캐시에서 읽음 (읽기 가격은 입력의 0.05~0.1배)
    # 위쪽 cache_control(자동)은 질문 안에서 SQL을 여러 번 돌릴 때 앞선 대화까지 캐시함
    system = SYSTEM
    if cache:
        system = [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]
        extra["cache_control"] = {"type": "ephemeral"}

    for _ in range(max_steps):
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=system,
            tools=tools,
            messages=messages,
            output_config={"effort": effort},
            **extra,
        )
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens
        usage["cache_read_input_tokens"] += response.usage.cache_read_input_tokens or 0
        usage["cache_creation_input_tokens"] += response.usage.cache_creation_input_tokens or 0
        out["model"] = response.model  # 실제로 답한 모델 (요청한 모델과 다를 수 있음)
        # AI의 응답(SQL 요청 포함)을 대화 기록에 그대로 붙임
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            out["answer"] = "".join(b.text for b in response.content if b.type == "text")
            out["stop_reason"] = response.stop_reason
            return out

        # AI가 요청한 SQL을 실행하고 결과를 돌려줌 (문서 검색 요청이면 검색 결과)
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            query = block.input["query"]
            if block.name == "search_docs":
                import rag
                hits = rag.search(query, min_score=-1)  # 모델이 직접 찾은 것이라 기준 점수 없이 상위 3개
                docs += [h["id"] for h in hits if h["id"] not in docs]
                if verbose:
                    print(f"\n[문서 검색] {query} → {[h['id'] for h in hits]}")
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": rag.to_prompt(hits)})
                continue
            if verbose:
                print(f"\n[SQL {len(sqls) + 1}]\n{query.strip()}")
            try:
                cols, rows = run_sql(query)
                sqls.append({"query": query, "cols": cols, "rows": rows})
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": to_text(cols, rows)})
            except (UnsafeSQL, duckdb.Error) as e:
                if verbose:
                    print(f"→ 오류: {e}")
                sqls.append({"query": query, "error": str(e)})
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": f"오류: {e}", "is_error": True})
        messages.append({"role": "user", "content": results})

    return out


if __name__ == "__main__":
    # 사용법: python agent.py "질문"   또는   python agent.py (대화 모드)
    if len(sys.argv) > 1:
        print("\n[답변]\n" + ask(" ".join(sys.argv[1:]))["answer"])
    else:
        while True:
            q = input("\n질문 (끝내려면 엔터): ").strip()
            if not q:
                break
            print("\n[답변]\n" + ask(q)["answer"])
