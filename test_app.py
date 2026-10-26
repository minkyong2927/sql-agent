"""API 서버 테스트 (AI는 가짜로 바꿔서 돌림 → 무료, 빠름)

python test_app.py
"""
from datetime import date

from fastapi.testclient import TestClient

import app as server


def fake_ask(question, model, verbose):
    return {
        "answer": f"가짜 답변: {question}",
        "sqls": [
            {"query": "SELECT 1", "cols": ["n", "d"], "rows": [(67, date(2026, 10, 25))]},
            {"query": "SELEC", "error": "문법 오류"},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "model": model,
    }


server.ask = fake_ask
client = TestClient(server.app)

checks = []


def check(name, cond):
    checks.append(cond)
    print(f"{'O' if cond else 'X'} {name}")


r = client.get("/health")
check("health 200", r.status_code == 200 and r.json() == {"status": "ok"})

r = client.post("/ask", json={"question": "지연 건수?", "model": "claude-haiku-5-5"})
d = r.json()
check("ask 200", r.status_code == 200)
check("답변 전달", d["answer"] == "가짜 답변: 지연 건수?")
check("SQL 결과 줄 (날짜는 글자로)", d["sqls"][0]["rows"] == [["67", "2026-10-25"]])
check("SQL 오류 전달", d["sqls"][1]["error"] == "문법 오류")
check("모델 지정", d["model"] == "claude-haiku-5-5")

r = client.post("/ask", json={"question": "지연 건수?", "model": "gpt-5"})
check("허용 안 된 모델 → 400", r.status_code == 400)

r = client.post("/ask", json={"question": "x" * 501})
check("너무 긴 질문 → 422", r.status_code == 422)

r = client.post("/ask", json={})
check("질문 없음 → 422", r.status_code == 422)

r = client.get("/")
check("화면 HTML", r.status_code == 200 and "데이터 질의 에이전트" in r.text)

print(f"\n{sum(checks)}/{len(checks)} 통과")
if not all(checks):
    raise SystemExit(1)  # 하나라도 실패하면 오류 코드로 끝냄 (CI가 빨간불)
