import duckdb

# 운영자가 물을 법한 질문과 정답 SQL
# 5단계 평가셋에서 "AI가 짠 SQL 결과 == 이 SQL 결과" 인지로 채점할 예정
QUESTIONS = [
    {
        "id": 1,
        "level": "쉬움",
        "question": "전체 고객은 몇 명이야?",
        "sql": """
            SELECT COUNT(*) AS 고객수
            FROM customers
        """,
    },
    {
        "id": 2,
        "level": "쉬움",
        "question": "고객이 가장 많은 지역 5곳 알려줘",
        "sql": """
            SELECT region AS 지역, COUNT(*) AS 고객수
            FROM customers
            GROUP BY region
            ORDER BY 고객수 DESC
            LIMIT 5
        """,
    },
    {
        "id": 3,
        "level": "쉬움",
        "question": "취소 사유별로 몇 건씩이야?",
        "sql": """
            SELECT reason AS 사유, COUNT(*) AS 건수
            FROM cancellations
            GROUP BY reason
            ORDER BY 건수 DESC
        """,
    },
    {
        "id": 4,
        "level": "보통",
        "question": "월별 가입 신청 건수 추이 보여줘",
        "sql": """
            SELECT strftime(applied_at, '%Y-%m') AS 월, COUNT(*) AS 가입신청
            FROM applications
            GROUP BY 월
            ORDER BY 월
        """,
    },
    {
        "id": 5,
        "level": "보통",
        "question": "가입률 높은 상담원 TOP 5 (상담 50건 이상)",
        "sql": """
            SELECT a.name AS 상담원, a.team AS 팀,
                   COUNT(*) AS 상담수,
                   ROUND(AVG(CASE WHEN c.result = '가입' THEN 1 ELSE 0 END) * 100, 1) AS 가입률
            FROM consultations AS c
            JOIN agents AS a ON c.agent_id = a.agent_id
            GROUP BY a.name, a.team
            HAVING COUNT(*) >= 50
            ORDER BY 가입률 DESC
            LIMIT 5
        """,
    },
    {
        "id": 6,
        "level": "보통",
        "question": "사은품 지급이 지연된 건은 몇 건이고 금액은 총 얼마야?",
        "sql": """
            SELECT COUNT(*) AS 지연건수, SUM(amount) AS 지연금액
            FROM gift_payouts
            WHERE status = '지연'
        """,
    },
    {
        "id": 7,
        "level": "어려움",
        "question": "통신사별 인터넷 가입 건수 (인터넷+TV 포함, 취소 제외)",
        "sql": """
            SELECT pv.name AS 통신사, COUNT(*) AS 가입건수
            FROM application_items AS i
            JOIN products     AS p  ON i.product_id = p.product_id
            JOIN providers    AS pv ON p.provider_id = pv.provider_id
            JOIN applications AS ap ON i.application_id = ap.application_id
            WHERE p.category IN ('인터넷', '인터넷+TV')
              AND ap.status <> '취소'
            GROUP BY pv.name
            ORDER BY 가입건수 DESC
        """,
    },
    {
        "id": 8,
        "level": "어려움",
        "question": "사은품 지급 지연된 고객 중 오래된 순으로 10명 연락처 줘",
        "sql": """
            SELECT cu.name AS 고객, cu.phone AS 전화번호, g.amount AS 금액, g.due_date AS 지급예정일
            FROM gift_payouts AS g
            JOIN applications AS ap ON g.application_id = ap.application_id
            JOIN customers    AS cu ON ap.customer_id = cu.customer_id
            WHERE g.status = '지연'
            ORDER BY g.due_date, g.payout_id
            LIMIT 10
        """,
    },
    {
        "id": 9,
        "level": "어려움",
        "question": "상담 신청 채널별로 가입까지 이어진 비율은?",
        "sql": """
            SELECT r.channel AS 채널,
                   COUNT(DISTINCT r.request_id) AS 신청수,
                   COUNT(DISTINCT ap.application_id) AS 가입수,
                   ROUND(COUNT(DISTINCT ap.application_id) * 100.0 / COUNT(DISTINCT r.request_id), 1) AS 전환율
            FROM consultation_requests AS r
            LEFT JOIN consultations AS c  ON c.request_id = r.request_id
            LEFT JOIN applications  AS ap ON ap.consultation_id = c.consultation_id
            GROUP BY r.channel
            ORDER BY 전환율 DESC
        """,
    },
    {
        "id": 10,
        "level": "어려움",
        "question": "인터넷 가입 건 중 휴대폰까지 같이 가입한 비율은?",
        "sql": """
            WITH per_app AS (
                SELECT i.application_id,
                       MAX(CASE WHEN p.category IN ('인터넷', '인터넷+TV') THEN 1 ELSE 0 END) AS has_net,
                       MAX(CASE WHEN p.category = '휴대폰' THEN 1 ELSE 0 END) AS has_phone
                FROM application_items AS i
                JOIN products AS p ON i.product_id = p.product_id
                GROUP BY i.application_id
            )
            SELECT SUM(has_net) AS 인터넷가입,
                   SUM(has_net * has_phone) AS 휴대폰결합,
                   ROUND(SUM(has_net * has_phone) * 100.0 / SUM(has_net), 1) AS 결합률
            FROM per_app
        """,
    },
    # ---------- 11~30: 평가셋용 추가 문항 ----------
    {
        "id": 11,
        "level": "쉬움",
        "question": "팀별 상담원 수 알려줘",
        "sql": """
            SELECT team AS 팀, COUNT(*) AS 상담원수
            FROM agents
            GROUP BY team
        """,
    },
    {
        "id": 12,
        "level": "쉬움",
        "question": "월 요금이 가장 비싼 상품 3개는?",
        "sql": """
            SELECT name AS 상품, monthly_fee AS 월요금
            FROM products
            ORDER BY monthly_fee DESC
            LIMIT 3
        """,
    },
    {
        "id": 13,
        "level": "쉬움",
        "question": "상담 결과별(가입·보류·거절) 건수는?",
        "sql": """
            SELECT result AS 결과, COUNT(*) AS 건수
            FROM consultations
            GROUP BY result
        """,
    },
    {
        "id": 14,
        "level": "쉬움",
        "question": "가입 신청 상태별 건수 보여줘",
        "sql": """
            SELECT status AS 상태, COUNT(*) AS 건수
            FROM applications
            GROUP BY status
        """,
    },
    {
        "id": 15,
        "level": "쉬움",
        "question": "통신사별로 상품이 몇 개씩 있어?",
        "sql": """
            SELECT pv.name AS 통신사, COUNT(*) AS 상품수
            FROM products AS p
            JOIN providers AS pv ON p.provider_id = pv.provider_id
            GROUP BY pv.name
        """,
    },
    {
        "id": 16,
        "level": "보통",
        "question": "이번 달(10월)에 들어온 상담 신청은 몇 건이야?",
        "sql": """
            SELECT COUNT(*) AS 신청수
            FROM consultation_requests
            WHERE requested_at >= '2026-10-01'
        """,
    },
    {
        "id": 17,
        "level": "보통",
        "question": "팀별 평균 상담 시간(분)을 소수 첫째 자리까지 알려줘",
        "sql": """
            SELECT a.team AS 팀, ROUND(AVG(c.duration_min), 1) AS 평균상담분
            FROM consultations AS c
            JOIN agents AS a ON c.agent_id = a.agent_id
            GROUP BY a.team
        """,
    },
    {
        "id": 18,
        "level": "보통",
        "question": "가입 신청이 가장 많은 지역 3곳은?",
        "sql": """
            SELECT cu.region AS 지역, COUNT(*) AS 가입신청
            FROM applications AS ap
            JOIN customers AS cu ON ap.customer_id = cu.customer_id
            GROUP BY cu.region
            ORDER BY 가입신청 DESC
            LIMIT 3
        """,
    },
    {
        "id": 19,
        "level": "보통",
        "question": "지금까지 지급 완료된 사은품 금액은 총 얼마야?",
        "sql": """
            SELECT SUM(amount) AS 지급완료금액
            FROM gift_payouts
            WHERE status = '지급완료'
        """,
    },
    {
        "id": 20,
        "level": "보통",
        "question": "렌탈에 관심 있다고 상담 신청한 건 중 실제 가입까지 간 건은 몇 건이야?",
        "sql": """
            SELECT COUNT(DISTINCT ap.application_id) AS 가입수
            FROM consultation_requests AS r
            JOIN consultations AS c  ON c.request_id = r.request_id
            JOIN applications  AS ap ON ap.consultation_id = c.consultation_id
            WHERE r.interest_category = '렌탈'
        """,
    },
    {
        "id": 21,
        "level": "보통",
        "question": "상담 신청하고 상담 시작까지 평균 몇 시간 걸렸어? 소수 첫째 자리까지",
        "sql": """
            SELECT ROUND(AVG(date_diff('minute', r.requested_at, c.started_at)) / 60, 1) AS 평균대기시간
            FROM consultations AS c
            JOIN consultation_requests AS r ON c.request_id = r.request_id
        """,
    },
    {
        "id": 22,
        "level": "보통",
        "question": "9월에 지급 완료된 사은품 금액 합계는?",
        "sql": """
            SELECT SUM(amount) AS 지급금액
            FROM gift_payouts
            WHERE status = '지급완료'
              AND paid_at >= '2026-09-01' AND paid_at < '2026-10-01'
        """,
    },
    {
        "id": 23,
        "level": "어려움",
        "question": "취소를 빼고 가입 건수가 가장 많은 상담원 3명 이름과 건수",
        "sql": """
            SELECT a.name AS 상담원, COUNT(*) AS 가입건수
            FROM applications AS ap
            JOIN consultations AS c ON ap.consultation_id = c.consultation_id
            JOIN agents AS a ON c.agent_id = a.agent_id
            WHERE ap.status <> '취소'
            GROUP BY a.name
            ORDER BY 가입건수 DESC
            LIMIT 3
        """,
    },
    {
        "id": 24,
        "level": "어려움",
        "question": "통신사별 휴대폰 상품 가입 건수 (취소 제외)",
        "sql": """
            SELECT pv.name AS 통신사, COUNT(*) AS 가입건수
            FROM application_items AS i
            JOIN products     AS p  ON i.product_id = p.product_id
            JOIN providers    AS pv ON p.provider_id = pv.provider_id
            JOIN applications AS ap ON i.application_id = ap.application_id
            WHERE p.category = '휴대폰' AND ap.status <> '취소'
            GROUP BY pv.name
        """,
    },
    {
        "id": 25,
        "level": "어려움",
        "question": "상담 신청 때 고른 관심 분야별로, 가입 신청 중 취소된 비율(%)은?",
        "sql": """
            SELECT r.interest_category AS 관심분야,
                   ROUND(AVG(CASE WHEN ap.status = '취소' THEN 1 ELSE 0 END) * 100, 1) AS 취소율
            FROM applications AS ap
            JOIN consultations AS c ON ap.consultation_id = c.consultation_id
            JOIN consultation_requests AS r ON c.request_id = r.request_id
            GROUP BY r.interest_category
        """,
    },
    {
        "id": 26,
        "level": "어려움",
        "question": "상담 신청을 한 번도 안 한 고객은 몇 명이야?",
        "sql": """
            SELECT COUNT(*) AS 고객수
            FROM customers AS cu
            WHERE NOT EXISTS (
                SELECT 1 FROM consultation_requests AS r WHERE r.customer_id = cu.customer_id
            )
        """,
    },
    {
        "id": 27,
        "level": "어려움",
        "question": "상담 신청을 3번 이상 한 고객은 몇 명이야?",
        "sql": """
            SELECT COUNT(*) AS 고객수
            FROM (
                SELECT customer_id FROM consultation_requests
                GROUP BY customer_id HAVING COUNT(*) >= 3
            )
        """,
    },
    {
        "id": 28,
        "level": "어려움",
        "question": "가입 신청 1건당 평균 상품 수는? 소수 둘째 자리까지",
        "sql": """
            SELECT ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT application_id), 2) AS 평균상품수
            FROM application_items
        """,
    },
    {
        "id": 29,
        "level": "어려움",
        "question": "인터넷+TV 상품 가입 건(취소 제외) 중 설치까지 끝난 비율(%)은?",
        "sql": """
            SELECT ROUND(AVG(CASE WHEN ap.status = '설치완료' THEN 1 ELSE 0 END) * 100, 1) AS 설치완료율
            FROM applications AS ap
            WHERE ap.status <> '취소'
              AND EXISTS (
                  SELECT 1 FROM application_items AS i
                  JOIN products AS p ON i.product_id = p.product_id
                  WHERE i.application_id = ap.application_id AND p.category = '인터넷+TV'
              )
        """,
    },
    {
        "id": 30,
        "level": "어려움",
        "question": "신청 월별로 상담 신청 대비 가입 신청 전환율(%) 추이 보여줘",
        "sql": """
            SELECT strftime(r.requested_at, '%Y-%m') AS 월,
                   ROUND(COUNT(DISTINCT ap.application_id) * 100.0 / COUNT(DISTINCT r.request_id), 1) AS 전환율
            FROM consultation_requests AS r
            LEFT JOIN consultations AS c  ON c.request_id = r.request_id
            LEFT JOIN applications  AS ap ON ap.consultation_id = c.consultation_id
            GROUP BY 월
            ORDER BY 월
        """,
    },
    # ---------- 31~40: 함정 문항 (level "함정", trap 에 함정 종류) ----------
    {
        "id": 31,
        "level": "함정",
        "trap": "상대 날짜",
        "question": "지난달 지급 완료된 사은품 총액은?",
        "sql": """
            SELECT SUM(amount) AS 지급금액
            FROM gift_payouts
            WHERE status = '지급완료'
              AND paid_at >= '2026-09-01' AND paid_at < '2026-10-01'
        """,
    },
    {
        "id": 32,
        "level": "함정",
        "trap": "건수 vs 사람 수",
        "question": "실제로 가입 신청까지 한 고객은 몇 명이야?",
        "sql": """
            SELECT COUNT(DISTINCT customer_id) AS 고객수
            FROM applications
        """,
    },
    {
        "id": 33,
        "level": "함정",
        "trap": "건수 vs 사람 수",
        "question": "가입 신청을 2번 이상 한 고객은 몇 명이야?",
        "sql": """
            SELECT COUNT(*) AS 고객수
            FROM (
                SELECT customer_id FROM applications
                GROUP BY customer_id HAVING COUNT(*) >= 2
            )
        """,
    },
    {
        "id": 34,
        "level": "함정",
        "trap": "JOIN 중복 합산",
        "question": "상품 2개를 같이 가입한 건들의 사은품 지급 완료 총액은?",
        "sql": """
            SELECT SUM(g.amount) AS 지급금액
            FROM gift_payouts AS g
            WHERE g.status = '지급완료'
              AND g.application_id IN (
                  SELECT application_id FROM application_items
                  GROUP BY application_id HAVING COUNT(*) = 2
              )
        """,
    },
    {
        "id": 35,
        "level": "함정",
        "trap": "그룹별 1등",
        "question": "팀별로 가입률이 가장 높은 상담원 한 명씩, 가입률(%)과 함께 알려줘",
        "sql": """
            WITH rate AS (
                SELECT a.team, a.name,
                       ROUND(AVG(CASE WHEN c.result = '가입' THEN 1 ELSE 0 END) * 100, 1) AS 가입률
                FROM consultations AS c
                JOIN agents AS a ON c.agent_id = a.agent_id
                GROUP BY a.team, a.name
            )
            SELECT team AS 팀, name AS 상담원, 가입률
            FROM rate
            QUALIFY ROW_NUMBER() OVER (PARTITION BY team ORDER BY 가입률 DESC) = 1
        """,
    },
    {
        "id": 36,
        "level": "함정",
        "trap": "증가율 계산",
        "question": "9월 대비 10월 가입 신청 건수 증가율(%)은? 소수 첫째 자리까지",
        "sql": """
            SELECT ROUND((oct - sep) * 100.0 / sep, 1) AS 증가율
            FROM (
                SELECT COUNT(*) FILTER (WHERE strftime(applied_at, '%Y-%m') = '2026-09') AS sep,
                       COUNT(*) FILTER (WHERE strftime(applied_at, '%Y-%m') = '2026-10') AS oct
                FROM applications
            )
        """,
    },
    {
        "id": 37,
        "level": "함정",
        "trap": "누적 합계",
        "question": "월별 가입 신청 누적 건수 추이 보여줘",
        "sql": """
            SELECT 월, SUM(건수) OVER (ORDER BY 월) AS 누적건수
            FROM (
                SELECT strftime(applied_at, '%Y-%m') AS 월, COUNT(*) AS 건수
                FROM applications
                GROUP BY 월
            )
            ORDER BY 월
        """,
    },
    {
        "id": 38,
        "level": "함정",
        "trap": "분모 선택",
        "question": "지급 예정일이 이미 지난 사은품 중에 아직 못 준(지연) 비율(%)은?",
        "sql": """
            SELECT ROUND(AVG(CASE WHEN status = '지연' THEN 1 ELSE 0 END) * 100, 1) AS 지연비율
            FROM gift_payouts
            WHERE due_date < '2026-10-25'  -- 기준일 당일은 아직 '지난' 게 아님
        """,
    },
    {
        "id": 39,
        "level": "함정",
        "trap": "없는 데이터",
        "question": "고객 연령대별 가입률 알려줘",
        "sql": None,  # 나이 칸이 없음 → "데이터가 없다"고 답해야 정답
    },
    {
        "id": 40,
        "level": "함정",
        "trap": "없는 데이터",
        "question": "상담원별 고객 만족도 평균 점수 순위 보여줘",
        "sql": None,  # 만족도 칸이 없음
    },
]

if __name__ == "__main__":
    con = duckdb.connect("ajd.duckdb", read_only=True)
    for q in QUESTIONS:
        print(f"\n[{q['id']}] ({q['level']}) {q['question']}")
        con.sql(q["sql"]).show()
