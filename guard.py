import sqlglot
from sqlglot import exp

DEFAULT_LIMIT = 200  # LIMIT 없는 SELECT에 강제로 붙일 최대 줄 수

# 조회 이외의 일을 하는 문장들: SQL 어디에 숨어 있어도 막음
FORBIDDEN = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge,
    exp.Create, exp.Drop, exp.Alter, exp.TruncateTable,
    exp.Copy, exp.Attach, exp.Detach, exp.Pragma, exp.Set, exp.Command,
)


class UnsafeSQL(Exception):
    """안전 검사에서 걸린 SQL"""


def check_sql(query, allowed_tables):
    """SQL을 검사해서 안전하면 (필요 시 LIMIT을 붙인) SQL을 돌려주고, 아니면 UnsafeSQL 을 던짐"""
    # 1) 문법 분석: 문법이 틀렸으면 여기서 걸림
    try:
        statements = sqlglot.parse(query, read="duckdb")
    except sqlglot.errors.SqlglotError as e:  # 문법 오류·글자 쪼개기 오류 모두
        raise UnsafeSQL(f"SQL 문법 오류: {e}")

    # 2) 한 번에 한 문장만: "SELECT 1; DROP TABLE x" 같은 끼워 넣기 차단
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise UnsafeSQL("SQL은 한 번에 한 문장만 실행할 수 있습니다")
    tree = statements[0]

    # 3) 조회(SELECT·UNION 등)만 허용
    if not isinstance(tree, exp.Query):
        raise UnsafeSQL(f"조회(SELECT) 문만 실행할 수 있습니다: {type(tree).__name__}")
    for node in tree.walk():
        if isinstance(node, FORBIDDEN):
            raise UnsafeSQL(f"허용되지 않는 명령이 들어 있습니다: {type(node).__name__}")

    # 4) 정해진 테이블만 허용: read_csv('C:/...') 같은 파일 읽기 차단
    cte_names = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise UnsafeSQL(f"테이블 자리에 함수·파일은 쓸 수 없습니다: {table.sql('duckdb')}")
        if table.name not in allowed_tables and table.name not in cte_names:
            raise UnsafeSQL(f"없는 테이블입니다: {table.name}")

    # 5) LIMIT이 없으면 붙임: 수백만 줄을 통째로 읽는 쿼리 방지
    if tree.args.get("limit") is None:
        tree = tree.limit(DEFAULT_LIMIT)

    return tree.sql(dialect="duckdb")
