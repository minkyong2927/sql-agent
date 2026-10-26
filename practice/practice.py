import duckdb

# 데이터베이스 파일 열기 (없으면 새로 만듦)
con = duckdb.connect("practice.duckdb")

# 다시 실행할 때를 대비해 기존 시트 지우기
con.execute("DROP TABLE IF EXISTS consultations")
con.execute("DROP TABLE IF EXISTS agents")

# 상담원 시트
con.execute("""
CREATE TABLE agents (
    agent_id INTEGER PRIMARY KEY,
    name     VARCHAR
)
""")

# 상담 기록 시트
con.execute("""
CREATE TABLE consultations (
    consultation_id INTEGER PRIMARY KEY,
    agent_id        INTEGER REFERENCES agents(agent_id),
    customer_id     INTEGER,
    started_at      TIMESTAMP,
    result          VARCHAR
)
""")

# 줄 넣기
con.execute("INSERT INTO agents VALUES (1, '김상담'), (2, '이상담')")
con.execute("""
INSERT INTO consultations VALUES
    (501, 1, 101, '2026-10-20 10:00', '보류'),
    (502, 2, 101, '2026-10-20 14:00', '가입'),
    (503, 2, 205, '2026-10-20 15:00', '거절')
""")

# 번호로 이어 붙여서 보기
con.sql("""
SELECT c.consultation_id, a.name, c.customer_id, c.result
FROM consultations AS c
JOIN agents AS a ON c.agent_id = a.agent_id
""").show()