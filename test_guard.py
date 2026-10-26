from guard import UnsafeSQL, check_sql

TABLES = {"customers", "applications", "gift_payouts"}

# (설명, SQL, 통과해야 하면 True)
CASES = [
    ("일반 조회", "SELECT COUNT(*) FROM customers", True),
    ("WITH 사용", "WITH t AS (SELECT * FROM applications) SELECT COUNT(*) FROM t", True),
    ("UNION", "SELECT name FROM customers UNION SELECT name FROM customers", True),
    ("삭제", "DELETE FROM customers", False),
    ("테이블 삭제", "DROP TABLE customers", False),
    ("끼워 넣기", "SELECT 1; DROP TABLE customers", False),
    ("수정", "UPDATE gift_payouts SET status = '지급완료'", False),
    ("파일로 내보내기", "COPY customers TO 'C:/Users/EST/leak.csv'", False),
    ("파일 읽기 (함수)", "SELECT * FROM read_csv('C:/Users/EST/.env')", False),
    ("파일 읽기 (경로)", "SELECT * FROM 'C:/Users/EST/.env'", False),
    ("다른 DB 붙이기", "ATTACH 'other.duckdb'", False),
    ("설정 변경", "SET enable_external_access = true", False),
    ("없는 테이블", "SELECT * FROM salaries", False),
    ("문법 오류", "SELEC * FROM customers", False),
    ("따옴표 안 닫힘", "SELECT * FROM customers WHERE name = '김 LIMIT 10", False),
]

passed = 0
for name, sql, should_pass in CASES:
    try:
        result = check_sql(sql, TABLES)
        ok = should_pass
        detail = result
    except UnsafeSQL as e:
        ok = not should_pass
        detail = f"차단: {e}"
    passed += ok
    print(f"{'O' if ok else 'X'} {name:12s} → {detail}")

print(f"\n{passed}/{len(CASES)} 통과")
