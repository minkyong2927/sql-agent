import os
import duckdb

# 매번 새로 만들기: 기존 DB 파일이 있으면 지움
if os.path.exists("ajd.duckdb"):
    os.remove("ajd.duckdb")

con = duckdb.connect("ajd.duckdb")

# ---------- 1단: 아무것도 참조하지 않는 테이블 ----------

# 통신사
con.execute("""
CREATE TABLE providers (
    provider_id INTEGER PRIMARY KEY,
    name        VARCHAR
)
""")

# 상담원
con.execute("""
CREATE TABLE agents (
    agent_id INTEGER PRIMARY KEY,
    name     VARCHAR,
    team     VARCHAR,
    hired_at DATE
)
""")

# 고객
con.execute("""
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name        VARCHAR,
    phone       VARCHAR,
    region      VARCHAR,
    created_at  TIMESTAMP
)
""")

# ---------- 2단: 통신사를 참조 ----------

# 상품 (category: 인터넷 / 인터넷+TV / 휴대폰 / 렌탈)
con.execute("""
CREATE TABLE products (
    product_id      INTEGER PRIMARY KEY,
    provider_id     INTEGER REFERENCES providers(provider_id),
    category        VARCHAR,
    name            VARCHAR,
    monthly_fee     INTEGER,
    contract_months INTEGER
)
""")

# ---------- 3단: 고객을 참조 ----------

# 상담 신청 (channel: 웹 / 앱 / 전화 / 카카오)
con.execute("""
CREATE TABLE consultation_requests (
    request_id        INTEGER PRIMARY KEY,
    customer_id       INTEGER REFERENCES customers(customer_id),
    channel           VARCHAR,
    interest_category VARCHAR,
    requested_at      TIMESTAMP
)
""")

# ---------- 4단: 상담 신청 + 상담원을 참조 ----------

# 상담 (result: 가입 / 보류 / 거절)
con.execute("""
CREATE TABLE consultations (
    consultation_id INTEGER PRIMARY KEY,
    request_id      INTEGER REFERENCES consultation_requests(request_id),
    agent_id        INTEGER REFERENCES agents(agent_id),
    started_at      TIMESTAMP,
    duration_min    INTEGER,
    result          VARCHAR
)
""")

# ---------- 5단: 상담 + 고객을 참조 ----------

# 가입 신청 (status: 접수 / 설치완료 / 개통완료 / 취소)
con.execute("""
CREATE TABLE applications (
    application_id  INTEGER PRIMARY KEY,
    consultation_id INTEGER REFERENCES consultations(consultation_id),
    customer_id     INTEGER REFERENCES customers(customer_id),
    applied_at      TIMESTAMP,
    status          VARCHAR
)
""")

# ---------- 6단: 가입 신청을 참조 ----------

# 가입 상품 목록 (한 신청에 상품 여러 개 가능)
con.execute("""
CREATE TABLE application_items (
    item_id        INTEGER PRIMARY KEY,
    application_id INTEGER REFERENCES applications(application_id),
    product_id     INTEGER REFERENCES products(product_id)
)
""")

# 설치 방문 (status: 예정 / 완료 / 지연 / 취소)
con.execute("""
CREATE TABLE installation_visits (
    visit_id       INTEGER PRIMARY KEY,
    application_id INTEGER REFERENCES applications(application_id),
    scheduled_at   TIMESTAMP,
    completed_at   TIMESTAMP,
    status         VARCHAR
)
""")

# 사은품 지급 (status: 대기 / 지급완료 / 지연)
con.execute("""
CREATE TABLE gift_payouts (
    payout_id      INTEGER PRIMARY KEY,
    application_id INTEGER REFERENCES applications(application_id),
    amount         INTEGER,
    due_date       DATE,
    paid_at        DATE,
    status         VARCHAR
)
""")

# 해지·취소
con.execute("""
CREATE TABLE cancellations (
    cancellation_id INTEGER PRIMARY KEY,
    application_id  INTEGER REFERENCES applications(application_id),
    cancelled_at    TIMESTAMP,
    reason          VARCHAR
)
""")

con.sql("SHOW TABLES").show()
