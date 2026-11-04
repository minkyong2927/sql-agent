# 사내 용어가 들어 있어 스키마만으로는 기준을 알 수 없는 질문 (정의는 knowledge/*.md 에만 있음)
# docs: 답하려면 검색되어야 하는 문서 조각 id (rag.py --eval 이 적중률을 잼)
KNOWLEDGE_QUESTIONS = [
    {
        "id": 101,
        "level": "지식",
        "question": "골든타임 응대율 알려줘",
        "docs": ["metrics#골든타임 응대율"],
        "sql": """
            SELECT ROUND(AVG(CASE WHEN c.started_at <= r.requested_at + INTERVAL 12 HOUR THEN 1 ELSE 0 END) * 100, 1) AS 골든타임응대율
            FROM consultation_requests AS r
            LEFT JOIN (SELECT request_id, MIN(started_at) AS started_at FROM consultations GROUP BY request_id) AS c
                   ON r.request_id = c.request_id
        """,
    },
    {
        "id": 102,
        "level": "지식",
        "question": "청약철회는 몇 건이야?",
        "docs": ["metrics#청약철회"],
        "sql": """
            SELECT COUNT(*) AS 청약철회
            FROM cancellations AS x
            JOIN applications AS a ON x.application_id = a.application_id
            WHERE x.cancelled_at <= a.applied_at + INTERVAL 24 HOUR
        """,
    },
    {
        "id": 103,
        "level": "지식",
        "question": "팀별 장기 상담 건수 보여줘",
        "docs": ["consult_ops#장기 상담"],
        "sql": """
            SELECT a.team AS 팀, COUNT(*) AS 장기상담
            FROM consultations AS c
            JOIN agents AS a ON c.agent_id = a.agent_id
            WHERE c.duration_min >= 35
            GROUP BY a.team
            ORDER BY 장기상담 DESC
        """,
    },
    {
        "id": 104,
        "level": "지식",
        "question": "신입 상담원 명단 알려줘",
        "docs": ["consult_ops#신입 상담원"],
        "sql": """
            SELECT name AS 상담원
            FROM agents
            WHERE hired_at >= DATE '2025-01-01'
            ORDER BY hired_at
        """,
    },
    {
        "id": 105,
        "level": "지식",
        "question": "고액 사은품은 몇 건이고 금액은 총 얼마야?",
        "docs": ["gift_policy#고액 사은품"],
        "sql": """
            SELECT COUNT(*) AS 건수, SUM(amount) AS 총액
            FROM gift_payouts
            WHERE amount >= 400000
        """,
    },
    {
        "id": 106,
        "level": "지식",
        "question": "사은품 SLA 위반 건수는?",
        "docs": ["gift_policy#사은품 SLA 위반"],
        "sql": """
            SELECT COUNT(*) AS SLA위반
            FROM gift_payouts
            WHERE paid_at > due_date
               OR (paid_at IS NULL AND due_date < DATE '2026-10-25')
        """,
    },
    {
        "id": 107,
        "level": "지식",
        "question": "가입 ARPU는 얼마야?",
        "docs": ["metrics#가입 ARPU"],
        "sql": """
            SELECT ROUND(AVG(fee)) AS ARPU
            FROM (
                SELECT a.application_id, SUM(p.monthly_fee) AS fee
                FROM applications AS a
                JOIN application_items AS i ON a.application_id = i.application_id
                JOIN products AS p ON i.product_id = p.product_id
                WHERE a.status <> '취소'
                GROUP BY a.application_id
            )
        """,
    },
    {
        "id": 108,
        "level": "지식",
        "question": "완료 전환율 몇 %야?",
        "docs": ["metrics#완료 전환율"],
        "sql": """
            SELECT ROUND(AVG(CASE WHEN status IN ('설치완료', '개통완료') THEN 1 ELSE 0 END) * 100, 1) AS 완료전환율
            FROM applications
        """,
    },
    {
        "id": 109,
        "level": "지식",
        "question": "디지털 채널로 들어온 상담 신청 비중(%)은?",
        "docs": ["consult_ops#채널 그룹"],
        "sql": """
            SELECT ROUND(AVG(CASE WHEN channel IN ('웹', '앱', '카카오') THEN 1 ELSE 0 END) * 100, 1) AS 디지털비중
            FROM consultation_requests
        """,
    },
    {
        "id": 110,
        "level": "지식",
        "question": "수도권 고객 중 순가입 고객은 몇 명이야?",
        "docs": ["consult_ops#권역", "metrics#순가입"],
        "sql": """
            SELECT COUNT(DISTINCT a.customer_id) AS 고객수
            FROM applications AS a
            JOIN customers AS cu ON a.customer_id = cu.customer_id
            WHERE cu.region IN ('서울', '경기', '인천') AND a.status <> '취소'
        """,
    },
    {
        "id": 111,
        "level": "지식",
        "question": "장기 약정 상품이 들어간 순가입 건수는?",
        "docs": ["gift_policy#장기 약정 상품", "metrics#순가입"],
        "sql": """
            SELECT COUNT(DISTINCT a.application_id) AS 건수
            FROM applications AS a
            JOIN application_items AS i ON a.application_id = i.application_id
            JOIN products AS p ON i.product_id = p.product_id
            WHERE p.contract_months >= 36 AND a.status <> '취소'
        """,
    },
    {
        "id": 112,
        "level": "지식",
        "question": "아직 아무도 응대 안 한 상담 신청이 몇 건이야?",
        "docs": ["consult_ops#미응대 신청"],
        "sql": """
            SELECT COUNT(*) AS 미응대
            FROM consultation_requests AS r
            WHERE NOT EXISTS (SELECT 1 FROM consultations AS c WHERE c.request_id = r.request_id)
        """,
    },
]

# 검색 점검용: 용어를 쓰지 않고 바꿔 말한 질문 (정답 SQL 없음, rag.py --eval 에서만 씀)
PARAPHRASES = [
    {"question": "신청하고 하루도 안 돼서 취소한 건 몇 건?", "docs": ["metrics#청약철회"]},
    {"question": "40만 원 넘게 준 사은품 몇 개야?", "docs": ["gift_policy#고액 사은품"]},
    {"question": "올해 새로 들어온 상담원 누구야?", "docs": ["consult_ops#신입 상담원"]},
    {"question": "약정 3년 이상 상품 가입 건수", "docs": ["gift_policy#장기 약정 상품"]},
    {"question": "사은품 약속한 날짜 못 지킨 거 몇 건이야?", "docs": ["gift_policy#사은품 SLA 위반"]},
    {"question": "서울 경기 인천 고객 몇 명이야?", "docs": ["consult_ops#권역"]},
    {"question": "고객 한 명이 한 달에 내는 요금 평균", "docs": ["metrics#가입 ARPU"]},
    {"question": "신청 들어오고 빨리 연락한 비율", "docs": ["metrics#골든타임 응대율"]},
]
