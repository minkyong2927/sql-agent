"""반복 측정·사람 채점 대조 계산 테스트 (API 호출 없음)

python test_stats.py
"""
from label import kappa
from repeat import compare, per_question

checks = []


def check(name, cond):
    checks.append(cond)
    print(f"{'O' if cond else 'X'} {name}")


def rows(passes):
    """{문항: [회차별 통과]} → results.jsonl 줄 모양"""
    return [{"id": i, "rep": k + 1, "judge_pass": p, "question": f"q{i}"}
            for i, ps in passes.items() for k, p in enumerate(ps)]


check("문항별 통과 기록을 회차 순서로", per_question(rows({1: [True, False, True]}))[1] == [True, False, True])

check("카파: 완전 일치 → 1", kappa([(True, True), (False, False), (True, True)]) == 1.0)
check("카파: 완전 반대 → 음수", kappa([(True, False), (False, True)]) < 0)
check("카파: 한쪽이 전부 통과면 일치가 많아도 0", kappa([(True, True), (True, True), (False, True)]) == 0.0)

same = rows({i: [True, False] for i in range(20)})
check("같은 결과끼리 비교 → 흔들림과 구별 안 됨", "구별 안 됨" in compare(same, same, "A", "B"))
worse = rows({i: [False] * 3 for i in range(20)})
better = rows({i: [True] * 3 for i in range(20)})
text = compare(worse, better, "A", "B")
check("전 문항 0% → 100% → 차이 있음, +100%", "차이 있음" in text and "+100.0%" in text)

print(f"\n{sum(checks)}/{len(checks)} 통과")
if not all(checks):
    raise SystemExit(1)
