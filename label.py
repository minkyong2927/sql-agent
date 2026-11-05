"""사람 채점 대조: 실제 에이전트 답변을 사람이 직접 채점하고 LLM 채점기와 얼마나 일치하는지 잼

judge.py --calibrate 는 일부러 만든 오답으로 검증한 것이라, 실제 답변에서도 사람 판단과 맞는지는 따로 재야 함.
채점 화면에는 LLM·규칙 채점 결과를 보여 주지 않음 (사람 판단이 끌려가지 않게).

python label.py --sample runs/<반복 실행 폴더> ...   채점할 답변 40개 뽑기 → labels/sample.jsonl
python label.py                                     한 건씩 보고 직접 채점 → labels/human.jsonl (중간에 멈춰도 이어서)
python label.py --report                            사람 vs LLM 채점기 vs 규칙 채점 일치율 → labels/report.md
"""
import argparse
import json
import random
import sys
from pathlib import Path

from eval import SETS
from judge import reference_text

LABEL_DIR = Path("labels")
SAMPLE = LABEL_DIR / "sample.jsonl"
HUMAN = LABEL_DIR / "human.jsonl"
SIZE = 40

RUBRIC = """채점 기준 (LLM 채점기와 같은 기준)
  통과 = 아래 두 가지를 모두 만족
   1) 질문이 직접 묻는 핵심 값이 참고 결과와 일치 (쉼표·만/억 표기·소수 첫째 자리 반올림 차이는 허용)
   2) 하나의 결론을 냄 (값을 후보로 늘어놓고 고르지 않거나, 다른 값을 주 답으로 내세우면 실패)
  참고 결과가 "데이터 없음"이면, 답변이 없다고 밝힐 때만 통과"""


def sample(run_dirs, seed=42):
    """LLM·규칙 채점이 갈린 답과 LLM 실패 답을 먼저 넣고, 나머지는 무작위로 채움 (같은 답변은 한 번만)"""
    rows, seen = [], set()
    for d in run_dirs:
        for line in open(Path(d) / "results.jsonl", encoding="utf-8"):
            r = json.loads(line)
            key = (r["id"], r["answer"].strip())
            if key not in seen and "judge_pass" in r:
                seen.add(key)
                rows.append({**r, "source": Path(d).name})
    rng = random.Random(seed)
    rng.shuffle(rows)
    # 절반은 어려운 답(규칙·LLM이 갈림 → LLM 실패 순), 절반은 나머지 → 통과·실패가 한쪽으로 쏠리지 않게
    split = [r for r in rows if r["answer_ok"] != r["judge_pass"]]
    failed = [r for r in rows if not r["judge_pass"] and r not in split]
    hard = (split + failed)[:SIZE // 2]
    rest = [r for r in rows if r not in hard]
    picked = hard + rest[:SIZE - len(hard)]
    rng.shuffle(picked)  # 어려운 것이 앞에 몰리지 않게
    LABEL_DIR.mkdir(exist_ok=True)
    with open(SAMPLE, "w", encoding="utf-8") as fp:
        for i, r in enumerate(picked, 1):
            fp.write(json.dumps({"no": i, "id": r["id"], "question": r["question"], "answer": r["answer"],
                                 "source": r["source"], "rep": r.get("rep"), "judge_pass": r["judge_pass"],
                                 "rule_pass": r["answer_ok"]}, ensure_ascii=False) + "\n")
    print(f"{len(picked)}건 → {SAMPLE} (전체 후보 {len(rows)}건 중, 채점이 갈렸거나 실패한 답 {len(hard)}건 포함)")


def load_jsonl(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")] if path.exists() else []


def label():
    questions = {q["id"]: q for q in SETS["all"]}
    items = load_jsonl(SAMPLE)
    done = {r["no"] for r in load_jsonl(HUMAN)}
    todo = [it for it in items if it["no"] not in done]
    print(RUBRIC)
    print(f"\n남은 {len(todo)}건 / 전체 {len(items)}건. 입력: 1=통과  2=실패  s=건너뜀  q=저장하고 끝내기\n")
    for it in todo:
        print("=" * 80)
        print(f"[{it['no']}/{len(items)}] 문항 {it['id']}: {it['question']}\n")
        print("--- 참고 결과 (정답 SQL 실행 결과) ---")
        print(reference_text(questions[it["id"]]))
        print("\n--- 채점할 답변 ---")
        print(it["answer"].strip())
        while True:
            key = input("\n판정 (1=통과 2=실패 s=건너뜀 q=끝): ").strip().lower()
            if key in ("1", "2", "s", "q"):
                break
        if key == "q":
            break
        if key == "s":
            continue
        note = input("메모 (없으면 엔터): ").strip()
        with open(HUMAN, "a", encoding="utf-8") as fp:
            fp.write(json.dumps({"no": it["no"], "human_pass": key == "1", "note": note}, ensure_ascii=False) + "\n")
    print(f"\n채점 {len(load_jsonl(HUMAN))}/{len(items)}건 저장됨 → python label.py --report")


def kappa(pairs):
    """코헨 카파: 우연히 맞을 확률을 뺀 일치도 (1 = 완전 일치, 0 = 우연 수준)"""
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    pa, pb = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def report(path=HUMAN):
    """path: 채점 파일 (기본 사람 채점, labels/opus.jsonl 은 다른 모델이 같은 기준으로 블라인드 채점한 것)"""
    items = {it["no"]: it for it in load_jsonl(SAMPLE)}
    labels = {r["no"]: r for r in load_jsonl(path)}  # 같은 건을 다시 채점했으면 마지막 것
    rows = [{**items[no], **lab} for no, lab in labels.items()]
    if not rows:
        sys.exit(f"{path} 에 채점이 없습니다. 먼저 python label.py")
    lines = [f"# 채점 대조: {path.name} ({len(rows)}건)", "",
             "| 채점기 | 채점자와 일치 | 코헨 카파 | 채점자 통과 · 채점기 실패 | 채점자 실패 · 채점기 통과 |", "|---|---|---|---|---|"]
    for name, key in [("LLM 채점기 (Sonnet)", "judge_pass"), ("규칙 채점", "rule_pass")]:
        pairs = [(r["human_pass"], r[key]) for r in rows]
        lines.append(f"| {name} | {sum(a == b for a, b in pairs)}/{len(rows)} | {kappa(pairs):.2f} | "
                     f"{sum(a and not b for a, b in pairs)} | {sum(b and not a for a, b in pairs)} |")
    lines.append(f"\n- 채점자 기준 통과 {sum(r['human_pass'] for r in rows)}/{len(rows)}")
    diff = [r for r in rows if r["human_pass"] != r["judge_pass"]]
    if diff:
        lines += ["", "## LLM 채점기와 채점자가 다르게 본 답", ""]
        for r in sorted(diff, key=lambda r: r["no"]):
            lines.append(f"- [{r['no']}] 문항 {r['id']} {r['question']} — 채점자 {'O' if r['human_pass'] else 'X'}, "
                         f"LLM {'O' if r['judge_pass'] else 'X'}, 규칙 {'O' if r['rule_pass'] else 'X'}"
                         + (f" · 메모: {r['note']}" if r["note"] else ""))
    text = "\n".join(lines)
    (LABEL_DIR / f"report_{path.stem}.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", nargs="+", metavar="RUN_DIR")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--labels", default=str(HUMAN), help="--report 에 쓸 채점 파일")
    args = ap.parse_args()
    if args.sample:
        sample(args.sample)
    elif args.report:
        report(Path(args.labels))
    else:
        label()
