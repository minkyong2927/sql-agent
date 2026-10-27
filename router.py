"""질문 난이도별 실행 예산

1. 분류: Haiku가 질문을 simple / complex 로 나눔 (스키마 요약만 보고, 아주 짧은 호출)
2. 예산: 난이도마다 모델·사고량(effort)·SQL 실행 횟수 한도를 다르게 줌
3. 승급: 정해진 예산으로 답을 못 내면(한도 초과, SQL이 전부 실패, 거절) Opus로 한 번 더

route=False 이면 분류 없이 바로 complex 예산으로 시작하고 실패할 때만 승급 (cascade)

python router.py "질문"
"""
import json
import sys

from agent import ALLOWED_TABLES, ask, client

ROUTER_MODEL = "claude-haiku-5-5"

BUDGETS = {
    # 한 테이블 집계·필터 정도: 싼 모델, 생각 적게, SQL 3회까지
    "simple": {"model": "claude-haiku-5-5", "effort": "low", "max_steps": 3},
    # 여러 테이블 JOIN, 비율·순위·기간 비교, 해석이 필요한 질문: 생각 더, SQL 6회까지
    "complex": {"model": "claude-haiku-5-5", "effort": "medium", "max_steps": 6},
}
# 위 예산으로 실패했을 때만 쓰는 상위 예산
ESCALATION = {"model": "claude-opus-5-5", "effort": "medium", "max_steps": 8}

ROUTER_SYSTEM = f"""운영 데이터 질문의 난이도를 분류합니다. SQL은 쓰지 않습니다.
DB 테이블: {", ".join(sorted(ALLOWED_TABLES))}

- simple: 테이블 하나(또는 단순 JOIN 하나)에서 건수·합계·목록을 조건으로 거르면 끝나는 질문
- complex: 여러 테이블을 이어야 하거나, 비율·증가율·순위·그룹별 1등·누적·기간 비교가 필요하거나,
  "실제로", "지난달"처럼 기준을 해석해야 하거나, DB에 없는 정보를 묻는 것처럼 보이는 질문
애매하면 complex."""

ROUTER_SCHEMA = {
    "type": "object",
    "properties": {
        "level": {"type": "string", "enum": ["simple", "complex"]},
        "reason": {"type": "string"},
    },
    "required": ["level", "reason"],
    "additionalProperties": False,
}


def classify(question):
    response = client.messages.create(
        model=ROUTER_MODEL,
        max_tokens=1000,
        system=ROUTER_SYSTEM,
        messages=[{"role": "user", "content": question}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": ROUTER_SCHEMA}},
    )
    v = json.loads(next(b.text for b in response.content if b.type == "text"))
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    return v["level"], v["reason"], {"model": response.model, "usage": usage}


def needs_escalation(out):
    """예산 안에서 답을 못 냈다고 볼 신호"""
    if out["stop_reason"] in ("max_steps", "refusal", "max_tokens"):
        return True
    sqls = out["sqls"]
    return bool(sqls) and all("error" in s for s in sqls)  # SQL을 시도했는데 하나도 성공 못 함


def merge_usage(calls):
    keys = ["input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"]
    return {k: sum(c["usage"].get(k, 0) for c in calls) for k in keys}


def ask_auto(question, verbose=True, allow_escalation=True, route=True):
    """난이도 분류 → 예산대로 실행 → 필요하면 승급. 비용 계산용으로 호출별 모델·토큰(calls)을 남김"""
    if route:
        level, reason, router_call = classify(question)
        calls = [router_call]
    else:
        level, reason, calls = "complex", "분류 생략 (cascade)", []
    budget = BUDGETS[level]
    if verbose:
        print(f"[분류] {level} — {reason}\n[예산] {budget}")
    out = ask(question, verbose=verbose, **budget)
    calls.append({"model": out["model"], "usage": out["usage"]})
    escalated = False
    if allow_escalation and needs_escalation(out):
        escalated = True
        if verbose:
            print(f"[승급] {out['stop_reason']}, SQL {len(out['sqls'])}회 → {ESCALATION}")
        out = ask(question, verbose=verbose, **ESCALATION)
        calls.append({"model": out["model"], "usage": out["usage"]})
    out.update({
        "route": level, "route_reason": reason, "escalated": escalated,
        "calls": calls, "usage": merge_usage(calls),
    })
    return out


if __name__ == "__main__":
    out = ask_auto(" ".join(sys.argv[1:]) or "지연된 설치 방문은 몇 건이야?")
    print("\n[답변]\n" + out["answer"])
    print(f"\n[호출] {[c['model'] for c in out['calls']]}")
