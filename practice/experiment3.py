import duckdb

con = duckdb.connect("practice.duckdb")

con.execute("INSERT INTO consultations VALUES (501, 1, 999, '2026-10-21 09:00', '가입')")
print("들어갔습니다")