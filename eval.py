"""평가셋 실행기

python eval.py --check              채점기 자체 점검 (API 호출 없음, 무료)
python eval.py --ids 1,7,9          일부 문항만 실행
python eval.py                      30문항 전체 실행 (기본 모델 claude-opus-5-5)
python eval.py --model claude-haiku-5-5
python eval.py --judge               규칙 채점 + LLM 채점(judge.py) 함께
python eval.py --model auto          난이도별 실행 예산(router.py)
python eval.py --model cascade       분류 없이 Haiku로 시작, 실패할 때만 Opus
"""
import argparse
import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from agent import ask, con, to_text
from questions import QUESTIONS

# 100만 토큰당 달러 (입력, 출력, 캐시 읽기). 캐시 쓰기는 입력의 1.25배
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
KRW_PER_USD = 1400  # 대략적인 환율 (원 환산 참고용)


# ---------- 정답 ----------

def gold_result(q):
    cur = con.cursor()
    cur.execute(q["sql"])
    return [d[0] for d in cur.description], cur.fetchall()


# ---------- 채점 1: SQL 결과 비교 ----------

def norm(v):
    """비교용으로 값 모양을 맞춤: 숫자는 소수 첫째 자리, 날짜는 글자"""
    if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
        return round(float(v), 1)
    if isinstance(v, (date, datetime)):
        return str(v)
    return str(v).strip()


def sql_match(gold_cols, gold_rows, sqls):
    """AI가 실행한 SQL 결과 중 하나라도, 정답의 모든 칸 값을 담고 있으면 통과
    (칸 이름·순서·추가 칸은 상관없음: 같은 답을 여러 방식으로 짤 수 있으므로)"""
    gold_columns = [Counter(norm(r[i]) for r in gold_rows) for i in range(len(gold_cols))]
    for s in sqls:
        if "rows" not in s or not s["rows"]:
            continue
        ai_columns = [Counter(norm(r[i]) for r in s["rows"]) for i in range(len(s["cols"]))]
        if all(any(not (g - a) for a in ai_columns) for g in gold_columns):
            return True
    return False


# ---------- 채점 2: 최종 답변 비교 ----------

def numbers_in(text):
    """답변 글에서 숫자를 모두 뽑음 (1,234 / 2,163만 / 1억 5,162만 같은 표기 포함)"""
    t = text.replace(",", "")
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    for eok, man in re.findall(r"(\d+(?:\.\d+)?)\s*억(?:\s*(\d+(?:\.\d+)?)\s*만)?", t):
        nums.append(float(eok) * 1e8 + (float(man) * 1e4 if man else 0))
    for man in re.findall(r"(\d+(?:\.\d+)?)\s*만", t):
        nums.append(float(man) * 1e4)
    return nums


def found_in_answer(v, answer, nums):
    if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
        return any(abs(n - float(v)) < 0.051 for n in nums)
    s = str(v).strip()
    compact = answer.replace(" ", "")
    if s.replace(" ", "") in compact:
        return True
    m = re.fullmatch(r"(\d{4})-(\d{2})", s)  # '2026-04' 는 '4월' 로 써도 인정
    return bool(m) and f"{int(m.group(2))}월" in compact


def answer_score(gold_rows, answer):
    """정답 표의 값(숫자·이름)이 답변에 몇 개 들어 있는지 → (전부 들어 있음?, 비율, 빠진 값)"""
    nums = numbers_in(answer)
    cells = [v for row in gold_rows for v in row]
    missing = [v for v in cells if not found_in_answer(v, answer, nums)]
    recall = 1 - len(missing) / len(cells) if cells else 0
    return not missing, round(recall, 3), missing


NO_DATA = re.compile(r"없습니다|없어|없음|존재하지 않|포함되어 있지 않|제공되지 않|알 수 없")


def grade(q, out):
    if q["sql"] is None:  # 없는 데이터를 묻는 문항: "데이터가 없다"고 답하면 정답
        ok = bool(NO_DATA.search(out["answer"]))
        return {"answer_ok": ok, "answer_recall": float(ok), "sql_ok": ok,
                "missing": [] if ok else ["'데이터가 없다'는 답변"]}
    cols, rows = gold_result(q)
    ok, recall, missing = answer_score(rows, out["answer"])
    return {
        "answer_ok": ok,                                 # 대표 점수: 답변에 정답 값이 전부 있음
        "answer_recall": recall,                         # 정답 값 중 답변에 들어간 비율
        "sql_ok": sql_match(cols, rows, out["sqls"]),    # 실행한 SQL 결과에 정답이 있음
        "missing": [str(m) for m in missing[:10]],
    }


# ---------- 실행 ----------

def trace_of(out):
    """대화 기록을 사람이 읽을 수 있는 JSON 목록으로"""
    turns = []
    for m in out["messages"]:
        content = m["content"]
        if isinstance(content, str):
            turns.append({"role": m["role"], "content": content})
            continue
        for b in content:
            b = b if isinstance(b, dict) else b.model_dump()
            if b["type"] == "text":
                turns.append({"role": "assistant", "content": b["text"]})
            elif b["type"] == "tool_use":
                turns.append({"role": "tool_call", "name": b["name"], "content": b["input"]["query"]})
            elif b["type"] == "tool_result":
                turns.append({"role": "tool_result", "content": b["content"]})
    return turns


def cost_usd(model, usage):
    p_in, p_out, p_read = PRICES.get(model, (0, 0, 0))
    return (usage["input_tokens"] * p_in + usage["output_tokens"] * p_out
            + usage.get("cache_read_input_tokens", 0) * p_read
            + usage.get("cache_creation_input_tokens", 0) * p_in * 1.25) / 1e6


def run_case(q, model, use_judge=False, cache=True):
    start = time.time()
    if model in ("auto", "cascade"):
        from router import ask_auto
        out = ask_auto(q["question"], verbose=False, route=model == "auto")
        cost = sum(cost_usd(c["model"], c["usage"]) for c in out["calls"])
    else:
        out = ask(q["question"], model=model, verbose=False, cache=cache)
        cost = cost_usd(out["model"], out["usage"])
    row = {
        "id": q["id"], "level": q["level"], "trap": q.get("trap"), "question": q["question"],
        "requested_model": model, "model": out["model"], "stop_reason": out["stop_reason"],
        "answer": out["answer"], "sql_count": len(out["sqls"]),
        "sql_errors": sum("error" in s for s in out["sqls"]),
        "usage": out["usage"], "cost_usd": round(cost, 5),
        "latency_s": round(time.time() - start, 1),
        **grade(q, out),
    }
    if model in ("auto", "cascade"):
        row.update({"route": out["route"], "escalated": out["escalated"],
                    "models": [c["model"] for c in out["calls"]],
                    "route_cost_usd": round(cost_usd(out["calls"][0]["model"], out["calls"][0]["usage"]), 6)
                    if model == "auto" else 0})
    if use_judge:
        from judge import judge  # judge.py가 이 파일을 불러오므로 여기서 불러옴
        row.update(judge(q, out["answer"]))
    return row, trace_of(out)


def self_check():
    """채점기 점검: 정답을 그대로 넣으면 100%, 빈 답이면 0%가 나와야 함"""
    oracle = null = wrong = 0
    answerable = [q for q in QUESTIONS if q["sql"] is not None]
    for i, q in enumerate(QUESTIONS):
        if q["sql"] is None:
            fake = {"answer": "요청하신 연령 정보는 DB에 없습니다.", "sqls": []}
        else:
            cols, rows = gold_result(q)
            fake = {"answer": to_text(cols, rows), "sqls": [{"query": q["sql"], "cols": cols, "rows": rows}]}
        g = grade(q, fake)
        oracle += g["answer_ok"] and g["sql_ok"]
        g = grade(q, {"answer": "", "sqls": []})
        null += g["answer_ok"] or g["sql_ok"]
        other = answerable[(i + 7) % len(answerable)]  # 다른 문항의 정답을 제출
        if other is q:
            other = answerable[(i + 8) % len(answerable)]
        oc, orows = gold_result(other)
        g = grade(q, {"answer": to_text(oc, orows), "sqls": [{"query": "", "cols": oc, "rows": orows}]})
        wrong += g["answer_ok"] or g["sql_ok"]
        if not grade(q, fake)["answer_ok"]:
            print("정답인데 틀림 처리:", q["id"], grade(q, fake)["missing"])
    n = len(QUESTIONS)
    print(f"정답 그대로 제출   → {oracle}/{n} 통과 (기대: {n}/{n})")
    print(f"빈 답 제출         → {null}/{n} 통과 (기대: 0/{n})")
    print(f"다른 문항 답 제출  → {wrong}/{n} 통과 (기대: 0에 가까움)")
    if oracle != n or null != 0 or wrong > 0:
        raise SystemExit(1)  # 채점기가 이상하면 오류 코드로 끝냄 (CI가 빨간불)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--ids", help="쉼표로 구분한 문항 번호 (예: 1,7,9)")
    ap.add_argument("--workers", type=int, default=4, help="동시에 돌릴 문항 수")
    ap.add_argument("--check", action="store_true", help="채점기 점검만 (API 호출 없음)")
    ap.add_argument("--judge", action="store_true", help="LLM 채점도 함께 (Sonnet, 문항당 약 $0.004)")
    ap.add_argument("--no-cache", action="store_true", help="프롬프트 캐싱 끄기 (비교용)")
    ap.add_argument("--tag", default="", help="실행 폴더 이름 뒤에 붙일 설명")
    args = ap.parse_args()

    if args.check:
        self_check()
        return

    qs = QUESTIONS
    if args.ids:
        ids = {int(x) for x in args.ids.split(",")}
        qs = [q for q in QUESTIONS if q["id"] in ids]

    run_dir = Path("runs") / f"{datetime.now():%m%d-%H%M%S}_{args.model}{'-' + args.tag if args.tag else ''}"
    (run_dir / "traces").mkdir(parents=True, exist_ok=True)
    print(f"{len(qs)}문항 × {args.model} → {run_dir}")

    rows, start = [], time.time()
    with ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(run_case, q, args.model, args.judge, not args.no_cache): q for q in qs}
        for f in as_completed(futures):
            q = futures[f]
            try:
                row, trace = f.result()
            except Exception as e:  # API 오류 등: 점수(0점)가 아니라 오류로 따로 기록
                with open(run_dir / "errors.jsonl", "a", encoding="utf-8") as fp:
                    fp.write(json.dumps({"id": q["id"], "error": repr(e)}, ensure_ascii=False) + "\n")
                print(f"  [{q['id']:2d}] 오류: {e}")
                continue
            rows.append(row)
            # 끝난 문항부터 바로 저장 (중간에 멈춰도 결과가 남음)
            with open(run_dir / "results.jsonl", "a", encoding="utf-8") as fp:
                fp.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            (run_dir / "traces" / f"{q['id']}.json").write_text(
                json.dumps(trace, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            mark = "O" if row["answer_ok"] else "X"
            jmark = f" LLM{'O' if row['judge_pass'] else 'X'}" if "judge_pass" in row else ""
            print(f"  [{q['id']:2d}] {mark} SQL{'O' if row['sql_ok'] else 'X'}{jmark} "
                  f"{row['latency_s']:5.1f}s ${row['cost_usd']:.4f}  {q['question']}")

    if not rows:
        return
    rows.sort(key=lambda r: r["id"])
    n = len(rows)
    total_cost = sum(r["cost_usd"] for r in rows)
    lines = [f"# {args.model} — {n}문항", ""]
    lines.append(f"- 답변 정답: **{sum(r['answer_ok'] for r in rows)}/{n}**")
    lines.append(f"- SQL 결과 정답: {sum(r['sql_ok'] for r in rows)}/{n}")
    if args.judge:
        from judge import judge_cost
        jc = judge_cost(rows)
        lines.append(f"- LLM 채점 통과: {sum(r['judge_pass'] for r in rows)}/{n} (채점 비용 ${jc:.3f} 별도)")
    tok = {k: sum(r["usage"].get(k, 0) for r in rows) for k in
           ["input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"]}
    lines.append(f"- 캐싱: {'끔' if args.no_cache else '켬'} · 입력 토큰 {tok['input_tokens']:,} + 캐시 읽기 "
                 f"{tok['cache_read_input_tokens']:,} + 캐시 쓰기 {tok['cache_creation_input_tokens']:,}, 출력 {tok['output_tokens']:,}")
    lines.append(f"- 비용: ${total_cost:.3f} (약 {total_cost * KRW_PER_USD:,.0f}원), "
                 f"문항당 평균 {sum(r['latency_s'] for r in rows) / n:.1f}초, 전체 {time.time() - start:.0f}초")
    mismatch = [r["id"] for r in rows if r["model"] != r["requested_model"] and r["requested_model"] not in ("auto", "cascade")]
    if mismatch:
        lines.append(f"- 주의: 요청과 다른 모델이 답한 문항 {mismatch}")
    lines += ["", "| 난이도 | 답변 정답 | SQL 정답 |", "|---|---|---|"]
    for level in ["쉬움", "보통", "어려움", "함정"]:
        lv = [r for r in rows if r["level"] == level]
        if lv:
            lines.append(f"| {level} | {sum(r['answer_ok'] for r in lv)}/{len(lv)} | {sum(r['sql_ok'] for r in lv)}/{len(lv)} |")
    if args.model in ("auto", "cascade"):
        rc = sum(r["route_cost_usd"] for r in rows)
        lines.append(f"- 분류 비용: ${rc:.4f} (전체의 {rc / total_cost:.0%}), Opus 승급 {sum(r['escalated'] for r in rows)}건")
        lines += ["", "| 난이도 | simple 배정 | complex 배정 | Opus 승급 |", "|---|---|---|---|"]
        for level in ["쉬움", "보통", "어려움", "함정"]:
            lv = [r for r in rows if r["level"] == level]
            if lv:
                lines.append(f"| {level} | {sum(r['route'] == 'simple' for r in lv)} | "
                             f"{sum(r['route'] == 'complex' for r in lv)} | {sum(r['escalated'] for r in lv)} |")
    wrong = [r for r in rows if not (r["answer_ok"] and r["sql_ok"] and r.get("judge_pass", True))]
    if wrong:
        lines += ["", "## 틀린 문항", ""]
        for r in wrong:
            trap = f" ({r['trap']})" if r.get("trap") else ""
            lines.append(f"- [{r['id']}]{trap} {r['question']} — 답변 {'O' if r['answer_ok'] else 'X'}, "
                         f"SQL {'O' if r['sql_ok'] else 'X'}, 빠진 값: {', '.join(r['missing']) or '-'}")
            if "judge_reason" in r:
                lines.append(f"  - LLM 채점 {'O' if r['judge_pass'] else 'X'}: {r['judge_reason']}")
    summary = "\n".join(lines)
    (run_dir / "summary.md").write_text(summary, encoding="utf-8")
    print("\n" + summary)


if __name__ == "__main__":
    main()
