import duckdb

con = duckdb.connect("practice.duckdb")

con.execute("INSERT INTO consultations VALUES (504, 9, 300, '2026-10-20 16:00', '보류')")
print("들어갔습니다")