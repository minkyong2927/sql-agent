"""반복 측정: 같은 평가를 N번 돌려 점수의 흔들림(편차)과 문항별 안정성을 봄

LLM 답은 매번 같지 않아서 1회 실행 점수만으로는 "개선됐다"고 말할 수 없음.
N번 돌려 평균·표준편차를 내고, 두 설정의 차이는 문항을 다시 뽑는 부트스트랩으로 95% 구간을 냄
(구간이 0을 포함하면 차이가 실행마다 생기는 흔들림과 구별되지 않는다는 뜻).

python repeat.py --set knowledge --knowledge none --n 5      반복 실행 (LLM 채점 포함)
python repeat.py --compare runs/<A> runs/<B>                두 반복 실행 비교 (API 호출 없음)
"""
import argparse
import json
import random
import statistics
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from eval import SETS, run_case
from pricing import KRW_PER_USD

BOOTSTRAP = 10000


def run_repeats(qs, model, knowledge, n, workers, run_dir):
    for rep in range(1, n + 1):
        start = time.time()
        with ThreadPoolExecutor(workers) as pool:
            rows = [r for r, _ in pool.map(lambda q: run_case(q, model, True, True, knowledge), qs)]
        with open(run_dir / "results.jsonl", "a", encoding="utf-8") as fp:
            for r in rows:
                fp.write(json.dumps({**r, "rep": rep}, ensure_ascii=False, default=str) + "\n")
        print(f"  {rep}회: LLM 채점 {sum(r['judge_pass'] for r in rows)}/{len(rows)}, "
              f"규칙 {sum(r['answer_ok'] for r in rows)}/{len(rows)}, "
              f"${sum(r['cost_usd'] for r in rows):.3f}, {time.time() - start:.0f}초")


def load(run_dir):
    return [json.loads(line) for line in open(Path(run_dir) / "results.jsonl", encoding="utf-8")]


def per_question(rows):
    """문항별 통과 기록 {id: [True, False, ...]} (LLM 채점 기준)"""
    out = defaultdict(list)
    for r in sorted(rows, key=lambda r: r["rep"]):
        out[r["id"]].append(r["judge_pass"])
    return out


def summarize(rows, title):
    reps = sorted({r["rep"] for r in rows})
    n_q = len({r["id"] for r in rows})
    scores = [sum(r["judge_pass"] for r in rows if r["rep"] == k) for k in reps]
    rules = [sum(r["answer_ok"] for r in rows if r["rep"] == k) for k in reps]
    costs = [sum(r["cost_usd"] for r in rows if r["rep"] == k) for k in reps]
    sd = statistics.stdev(scores) if len(scores) > 1 else 0.0
    lines = [f"# {title}", "",
             f"- {len(reps)}회 반복 × {n_q}문항 (LLM 채점 기준)",
             f"- 회차별 통과: {', '.join(map(str, scores))} → 평균 **{statistics.mean(scores):.1f}/{n_q}**, "
             f"표준편차 {sd:.2f}, 범위 {min(scores)}~{max(scores)}",
             f"- 규칙 채점 회차별: {', '.join(map(str, rules))}",
             f"- 1회 평균 비용 ${statistics.mean(costs):.4f} (약 {statistics.mean(costs) * KRW_PER_USD:,.0f}원, 채점 비용 제외)"]
    flaky = {i: v for i, v in per_question(rows).items() if 0 < sum(v) < len(v)}
    always_fail = [i for i, v in per_question(rows).items() if not any(v)]
    lines.append(f"- 매번 통과 {n_q - len(flaky) - len(always_fail)}문항 · 회차마다 갈림 {len(flaky)}문항 · 매번 실패 {len(always_fail)}문항")
    questions = {r["id"]: r["question"] for r in rows}
    if flaky or always_fail:
        lines += ["", "| 문항 | 통과 | 질문 |", "|---|---|---|"]
        for i in sorted(flaky) + sorted(always_fail):
            v = per_question(rows)[i]
            lines.append(f"| {i} | {sum(v)}/{len(v)} | {questions[i]} |")
    return "\n".join(lines)


def compare(rows_a, rows_b, name_a, name_b, seed=0):
    """문항별 통과율 차이(B − A)의 평균과 부트스트랩 95% 구간 (같은 문항끼리 짝지어 비교)"""
    a, b = per_question(rows_a), per_question(rows_b)
    ids = sorted(set(a) & set(b))
    diff = [sum(b[i]) / len(b[i]) - sum(a[i]) / len(a[i]) for i in ids]
    rng = random.Random(seed)
    boots = sorted(statistics.mean(rng.choice(diff) for _ in ids) for _ in range(BOOTSTRAP))
    lo, hi = boots[int(BOOTSTRAP * 0.025)], boots[int(BOOTSTRAP * 0.975)]
    mean = statistics.mean(diff)
    verdict = "차이 있음 (구간이 0을 포함하지 않음)" if lo > 0 or hi < 0 else "흔들림과 구별 안 됨 (구간이 0을 포함)"
    rate = lambda d: sum(sum(v) for v in d.values()) / sum(len(v) for v in d.values())
    return "\n".join([
        f"# 비교: {name_a} → {name_b}", "",
        f"- 통과율 {rate(a):.1%} → {rate(b):.1%} ({len(ids)}문항 짝 비교)",
        f"- 문항당 통과율 차이 평균 {mean:+.1%}, 부트스트랩 95% 구간 [{lo:+.1%}, {hi:+.1%}] → {verdict}",
        f"- 좋아진 문항 {sum(d > 0 for d in diff)} · 나빠진 문항 {sum(d < 0 for d in diff)} · 같음 {sum(d == 0 for d in diff)}",
    ])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="cascade")
    ap.add_argument("--set", default="base", choices=SETS)
    ap.add_argument("--knowledge", default="rag", choices=["rag", "full", "none"])
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tag", default="")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"), help="반복 실행 폴더 두 개 비교")
    args = ap.parse_args()

    if args.compare:
        a, b = args.compare
        text = compare(load(a), load(b), Path(a).name, Path(b).name)
        print(text)
        return

    name = f"{datetime.now():%m%d-%H%M%S}_repeat-{args.model}-{args.set}-{args.knowledge}{'-' + args.tag if args.tag else ''}"
    run_dir = Path("runs") / name
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"{args.set} × {args.n}회 ({args.model}, 문서 {args.knowledge}) → {run_dir}")
    run_repeats(SETS[args.set], args.model, args.knowledge, args.n, args.workers, run_dir)
    text = summarize(load(run_dir), f"{args.model} — {args.set} · 사내 문서 {args.knowledge} · {args.n}회 반복")
    (run_dir / "summary.md").write_text(text, encoding="utf-8")
    print("\n" + text)


if __name__ == "__main__":
    main()
