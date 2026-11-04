"""서버 로그 집계: 요청 수·상태·응답 시간(p50/p95)·비용·SQL 오류율

Render 로그를 내려받은 파일이나 붙여 넣은 텍스트에서 {"event": "ask", ...} 줄만 골라 집계
(줄 앞에 타임스탬프 같은 접두어가 붙어 있어도 됨)

python log_report.py render-logs.txt
type render-logs.txt | python log_report.py
"""
import json
import sys
from collections import Counter

from pricing import KRW_PER_USD


def parse(lines):
    recs = []
    for line in lines:
        i = line.find("{")
        if i < 0:
            continue
        try:
            rec = json.loads(line[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("event") == "ask":
            recs.append(rec)
    return recs


def percentile(values, p):
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))]


def report(recs):
    if not recs:
        return "ask 로그 없음"
    ok = [r for r in recs if r.get("status") == 200]
    status = Counter(r.get("status") for r in recs)
    lat = [r["latency_s"] for r in ok if "latency_s" in r]
    cost = sum(r.get("cost_usd", 0) for r in ok)
    n_sql = sum(r.get("n_sql", 0) for r in ok)
    n_err = sum(r.get("n_sql_error", 0) for r in ok)
    days = sorted({r["ts"][:10] for r in recs if "ts" in r})
    lines = [
        f"# 서버 로그 집계 ({days[0]} ~ {days[-1]})" if days else "# 서버 로그 집계",
        "",
        f"- 요청: {len(recs)}건 · 성공 {len(ok)}건 · 사용자 {len({r.get('ip') for r in recs})}명(IP 해시 기준)",
        "- 상태: " + ", ".join(f"{k} {v}건" for k, v in sorted(status.items(), key=lambda x: str(x[0]))),
        f"- 응답 시간: p50 {percentile(lat, 0.5):.1f}초 · p95 {percentile(lat, 0.95):.1f}초 · 최대 {max(lat, default=0):.1f}초",
        f"- 비용: ${cost:.4f} (약 {cost * KRW_PER_USD:,.0f}원) · 성공 1건당 ${cost / max(len(ok), 1):.5f}",
        f"- SQL: 성공 1건당 {n_sql / max(len(ok), 1):.1f}회 실행 · 실행 오류 {n_err}/{n_sql}"
        + (f" ({n_err / n_sql:.0%})" if n_sql else ""),
    ]
    stops = Counter(r.get("stop_reason") for r in ok)
    if set(stops) - {"end_turn"}:
        lines.append("- 끝난 이유: " + ", ".join(f"{k} {v}건" for k, v in stops.most_common()))
    errors = Counter(r.get("error") for r in recs if r.get("status") != 200)
    if errors:
        lines += ["", "## 실패 사유"] + [f"- {e}: {n}건" for e, n in errors.most_common()]
    slow = sorted(ok, key=lambda r: r.get("latency_s", 0), reverse=True)[:3]
    lines += ["", "## 가장 느린 요청"] + [
        f"- {r.get('latency_s')}초 · SQL {r.get('n_sql')}회 · {r.get('request_id')} · {r.get('question')}" for r in slow]
    return "\n".join(lines)


if __name__ == "__main__":
    src = open(sys.argv[1], encoding="utf-8") if len(sys.argv) > 1 else sys.stdin
    print(report(parse(src)))
