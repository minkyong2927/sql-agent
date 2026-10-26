import random
from datetime import date, datetime, timedelta

import duckdb

# 같은 숫자로 시작하면 매번 같은 가짜 데이터가 나옴 (재현 가능)
random.seed(42)

# 데이터 기준일: 이 날짜 이후 일은 아직 안 일어난 것으로 처리
TODAY = datetime(2026, 10, 25, 18, 0)
START = datetime(2026, 4, 1, 9, 0)

con = duckdb.connect("ajd.duckdb")


def random_time(start, end):
    """start~end 사이 임의의 시각 (업무 시간 9~20시)"""
    days = max(0, (end - start).days)
    d = start + timedelta(days=random.randint(0, days))
    d = d.replace(hour=random.randint(9, 19), minute=random.choice([0, 10, 20, 30, 40, 50]))
    return max(d, start)  # 시각을 바꾸다 start보다 앞서지 않게


def korean_name():
    last = random.choice("김이박최정강조윤장임한오서신권황안송류홍")
    first = random.choice("민서지수현예하도윤준") + random.choice("준우진영아은희호연빈")
    return last + first


# ---------- 1단 ----------

providers = [(1, "SKT"), (2, "KT"), (3, "LG U+"), (4, "SK브로드밴드"), (5, "LG헬로비전")]
con.executemany("INSERT INTO providers VALUES (?, ?)", providers)

teams = ["인터넷1팀", "인터넷2팀", "모바일팀", "렌탈팀"]
agents = []
for i in range(1, 21):
    hired = date(2023, 1, 1) + timedelta(days=random.randint(0, 1000))
    agents.append((i, korean_name(), teams[(i - 1) % 4], hired))
con.executemany("INSERT INTO agents VALUES (?, ?, ?, ?)", agents)

regions = ["서울", "경기", "인천", "부산", "대구", "대전", "광주", "울산", "강원", "충남", "전남", "경북", "경남", "제주"]
region_weights = [25, 27, 6, 7, 5, 3, 3, 2, 3, 4, 3, 4, 6, 2]
customers = []
for i in range(1, 2001):
    phone = f"010-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}"
    region = random.choices(regions, region_weights)[0]
    customers.append((i, korean_name(), phone, region, random_time(START, TODAY - timedelta(days=1))))
con.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?)", customers)

# ---------- 2단 ----------

# (통신사, 분류, 이름, 월요금, 약정개월)
product_specs = [
    (1, "휴대폰", "SKT 5GX 프라임", 89000, 24), (1, "휴대폰", "SKT 5G 베이직", 55000, 24),
    (2, "휴대폰", "KT 5G 초이스", 90000, 24), (2, "휴대폰", "KT 5G 슬림", 55000, 24),
    (3, "휴대폰", "U+ 5G 프리미어", 85000, 24), (3, "휴대폰", "U+ 5G 라이트", 55000, 24),
    (2, "인터넷", "KT 인터넷 500M", 33000, 36), (2, "인터넷", "KT 인터넷 1G", 38500, 36),
    (3, "인터넷", "U+ 인터넷 500M", 33000, 36), (3, "인터넷", "U+ 인터넷 1G", 38500, 36),
    (4, "인터넷", "SKB 인터넷 500M", 33000, 36), (4, "인터넷", "SKB 인터넷 1G", 38500, 36),
    (5, "인터넷", "헬로 인터넷 500M", 25300, 36),
    (2, "인터넷+TV", "KT 인터넷+지니TV", 49500, 36), (3, "인터넷+TV", "U+ 인터넷+U+tv", 49500, 36),
    (4, "인터넷+TV", "SKB 인터넷+B tv", 49500, 36), (5, "인터넷+TV", "헬로 인터넷+헬로tv", 39600, 36),
    (1, "렌탈", "정수기 렌탈", 29900, 60), (1, "렌탈", "공기청정기 렌탈", 25900, 60),
    (2, "렌탈", "비데 렌탈", 19900, 60),
]
products = [(i + 1, *spec) for i, spec in enumerate(product_specs)]
con.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?)", products)
products_by_cat = {}
for p in products:
    products_by_cat.setdefault(p[2], []).append(p)

# ---------- 3단 ----------

categories = ["인터넷", "인터넷+TV", "휴대폰", "렌탈"]
requests = []
for i in range(1, 3001):
    cust = random.choice(customers)
    t = random_time(cust[4], TODAY - timedelta(days=1))
    channel = random.choices(["웹", "앱", "전화", "카카오"], [35, 30, 15, 20])[0]
    interest = random.choices(categories, [35, 30, 25, 10])[0]
    requests.append((i, cust[0], channel, interest, t))
con.executemany("INSERT INTO consultation_requests VALUES (?, ?, ?, ?, ?)", requests)

# ---------- 4단 ----------

team_of_cat = {"인터넷": ["인터넷1팀", "인터넷2팀"], "인터넷+TV": ["인터넷1팀", "인터넷2팀"],
               "휴대폰": ["모바일팀"], "렌탈": ["렌탈팀"]}
consultations = []
cid = 1
for req in requests:
    if random.random() < 0.15:  # 15%는 상담 연결 안 됨
        continue
    t = req[4] + timedelta(hours=random.randint(1, 48))
    if t > TODAY:
        continue
    agent = random.choice([a for a in agents if a[2] in team_of_cat[req[3]]])
    # 상담원마다 실력 차이: 번호가 낮을수록 가입률이 조금 높게
    join_rate = 0.55 - agent[0] * 0.01
    result = random.choices(["가입", "보류", "거절"], [join_rate, 0.25, 0.75 - join_rate])[0]
    consultations.append((cid, req[0], agent[0], t, random.randint(5, 40), result))
    cid += 1
con.executemany("INSERT INTO consultations VALUES (?, ?, ?, ?, ?, ?)", consultations)

# ---------- 5단 + 6단 ----------

request_by_id = {r[0]: r for r in requests}
applications, items, visits, payouts, cancels = [], [], [], [], []
gift_range = {"인터넷": (300000, 450000), "인터넷+TV": (400000, 550000),
              "휴대폰": (100000, 200000), "렌탈": (30000, 80000)}
cancel_reasons = ["단순 변심", "타사 조건이 더 좋음", "설치 일정 불만", "이사 계획 변경", "요금 부담"]

for con_row in consultations:
    if con_row[5] != "가입":
        continue
    app_id = len(applications) + 1
    req = request_by_id[con_row[1]]
    applied_at = con_row[3] + timedelta(minutes=con_row[4])

    # 가입 상품: 관심 분야 상품 1개 + 30%는 휴대폰 결합
    main = random.choice(products_by_cat[req[3]])
    chosen = [main]
    if req[3] != "휴대폰" and random.random() < 0.3:
        chosen.append(random.choice(products_by_cat["휴대폰"]))
    for p in chosen:
        items.append((len(items) + 1, app_id, p[0]))

    cancelled = random.random() < 0.08
    needs_visit = any(p[2] != "휴대폰" for p in chosen)
    done_at = None  # 설치 또는 개통 완료 시각

    if needs_visit:
        scheduled = (applied_at + timedelta(days=random.randint(2, 7))).replace(hour=random.choice([10, 13, 15]), minute=0)
        if cancelled:
            visit = (scheduled, None, "취소")
        elif scheduled > TODAY:
            visit = (scheduled, None, "예정")
        elif random.random() < 0.1:  # 10%는 설치 지연
            late = scheduled + timedelta(days=random.randint(2, 10))
            visit = (scheduled, late if late <= TODAY else None, "지연" if late > TODAY else "완료")
        else:
            visit = (scheduled, scheduled + timedelta(hours=1), "완료")
        visits.append((len(visits) + 1, app_id, *visit))
        done_at = visit[1]
    elif not cancelled:
        done_at = applied_at + timedelta(days=1)  # 휴대폰만: 다음 날 개통

    if cancelled:
        status = "취소"
        cancel_at = applied_at + timedelta(days=random.randint(1, 5))
        cancels.append((len(cancels) + 1, app_id, min(cancel_at, TODAY), random.choice(cancel_reasons)))
    elif done_at is None or done_at > TODAY:
        status = "접수"
    else:
        status = "설치완료" if needs_visit else "개통완료"
    applications.append((app_id, con_row[0], req[1], applied_at, status))

    # 사은품: 설치/개통 완료 건만, 완료 30일 뒤 지급 예정
    if status in ("설치완료", "개통완료"):
        amount = round(random.randint(*gift_range[main[2]]), -4)
        due = (done_at + timedelta(days=30)).date()
        if due > TODAY.date():
            payout = (None, "대기")
        elif random.random() < 0.12:  # 12%는 지급 지연
            payout = (None, "지연")
        else:
            payout = (due + timedelta(days=random.randint(0, 3)), "지급완료")
        payouts.append((len(payouts) + 1, app_id, amount, due, *payout))

con.executemany("INSERT INTO applications VALUES (?, ?, ?, ?, ?)", applications)
con.executemany("INSERT INTO application_items VALUES (?, ?, ?)", items)
con.executemany("INSERT INTO installation_visits VALUES (?, ?, ?, ?, ?)", visits)
con.executemany("INSERT INTO gift_payouts VALUES (?, ?, ?, ?, ?, ?)", payouts)
con.executemany("INSERT INTO cancellations VALUES (?, ?, ?, ?)", cancels)

# 테이블별 줄 수 확인
for t in ["providers", "agents", "customers", "products", "consultation_requests", "consultations",
          "applications", "application_items", "installation_visits", "gift_payouts", "cancellations"]:
    print(f"{t:24s}", con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
