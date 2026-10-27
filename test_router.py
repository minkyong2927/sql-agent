"""승급 판단·토큰 합산 테스트 (API 호출 없음, 무료)

python test_router.py
"""
from router import needs_escalation, merge_usage

checks = []


def check(name, cond):
    checks.append(cond)
    print(f"{'O' if cond else 'X'} {name}")


ok = {"query": "SELECT 1", "cols": ["n"], "rows": [(1,)]}
err = {"query": "SELEC", "error": "문법 오류"}

check("정상 답변 → 승급 안 함", not needs_escalation({"stop_reason": "end_turn", "sqls": [ok]}))
check("SQL 없이 답변(없는 데이터) → 승급 안 함", not needs_escalation({"stop_reason": "end_turn", "sqls": []}))
check("오류 뒤 고쳐서 성공 → 승급 안 함", not needs_escalation({"stop_reason": "end_turn", "sqls": [err, ok]}))
check("실행 횟수 한도 초과 → 승급", needs_escalation({"stop_reason": "max_steps", "sqls": [ok, ok, ok]}))
check("SQL 전부 실패 → 승급", needs_escalation({"stop_reason": "end_turn", "sqls": [err, err]}))
check("거절 → 승급", needs_escalation({"stop_reason": "refusal", "sqls": []}))

u = merge_usage([
    {"model": "a", "usage": {"input_tokens": 10, "output_tokens": 1}},
    {"model": "b", "usage": {"input_tokens": 5, "output_tokens": 2, "cache_read_input_tokens": 100}},
])
check("호출별 토큰 합산", u == {"input_tokens": 15, "output_tokens": 3,
                                 "cache_read_input_tokens": 100, "cache_creation_input_tokens": 0})

print(f"\n{sum(checks)}/{len(checks)} 통과")
if not all(checks):
    raise SystemExit(1)
