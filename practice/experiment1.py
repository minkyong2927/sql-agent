import duckdb

con = duckdb.connect("practice.duckdb")

con.sql("""
SELECT a.name, COUNT(*) AS 상담건수
FROM consultations AS c
JOIN agents AS a ON c.agent_id = a.agent_id
GROUP BY a.name
""").show()