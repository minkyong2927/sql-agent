# 데이터 질의 에이전트 (text-to-SQL)

통신·렌탈 가입 중개 서비스의 운영 데이터를 말로 물으면, Claude가 SQL을 짜서 실행하고 결과를 근거로 답하는 에이전트.

```
질문: 사은품 지급 지연된 건 몇 건이고 총 얼마야?
  → Claude: run_sql 도구로 SELECT ... FROM gift_payouts WHERE status = '지연'
  → 실행 결과: 67 | 21630000
답변: 사은품 지급이 지연된 건은 67건, 총 21,630,000원입니다.
```

## 구성

| 파일 | 역할 |
|---|---|
| `schema.py` / `seed.py` | DuckDB 테이블 11개 생성 + 가상 데이터 생성 (고객 2,000명, 상담 2,514건, 가입 1,137건 등, 시드 고정) |
| `agent.py` | Claude API tool use 에이전트. 직접 구현한 루프, SQL 오류 시 모델이 스스로 수정, 실행 횟수·결과 크기 제한 |
| `guard.py` | sqlglot 기반 SQL 검사: 한 문장·조회문만, 금지 명령 차단, 테이블 허용 목록(파일 읽기 차단), LIMIT 강제 |
| `questions.py` | 평가 문항 40개 + 정답 SQL (쉬움 8 · 보통 10 · 어려움 12 · 함정 10) |
| `eval.py` | 평가 실행기: 답변 정답 / SQL 결과 정답 2종 채점, 병렬 실행, 문항별 결과·대화 기록 저장 |
| `app.py` | FastAPI 서버 (`POST /ask`, `GET /health`, 시연 화면 `/`) |
| `test_*.py` | 안전장치 15건, API 10건 테스트 (API 테스트는 AI 호출을 가짜로 바꿔 무료) |

## 안전장치

1. **SQL 검사 (guard.py)**: `DELETE`·`DROP`·`COPY`·`ATTACH`·`SET` 등 차단, `SELECT 1; DROP ...` 끼워 넣기 차단, `read_csv('...')` 같은 로컬 파일 접근 차단
2. **DB 연결**: 읽기 전용 + 외부 접근 금지 (`enable_external_access=False`)
3. **실행 제한**: LIMIT 200 자동 부여, 모델에는 50줄까지, 질문당 SQL 8회까지

## 평가 결과 (각 1회 실행)

| 실험 | 모델 | 답변 정답 | SQL 결과 정답 | 비용 |
|---|---|---|---|---|
| 기준선 (1~30번) | Opus 5.5 | 30/30 | 27/30 | $0.82 |
| v1: "계산은 SQL 안에서" 규칙 추가 | Opus 5.5 | 30/30 | 30/30 | $0.80 |
| v1 | Haiku 5.5 | 30/30 | 30/30 | $0.02 |
| 함정 10문항 (31~40번) | Opus 5.5 | 10/10 | 10/10 | $0.32 |
| 함정 10문항 (31~40번) | Haiku 5.5 | 10/10 | 10/10 | $0.01 |

- 기준선의 SQL 결과 오답 3건은 비율을 SQL이 아닌 모델이 직접 계산한 경우였고, 프롬프트 규칙 한 줄로 해결
- Haiku 실행 중 guard.py가 sqlglot `TokenError`를 처리하지 않는 버그를 발견해 수정 (`runs/*haiku-5-5-v1/errors-before-guard-fix.jsonl`)
- 함정 38번의 오답은 정답 SQL의 경계 조건(`<=`) 오류였음 → 수정

## 실행

```
python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
```

`.env` 파일에 `ANTHROPIC_API_KEY=...` 를 넣은 뒤:

```
python schema.py && python seed.py      # DB 생성
python agent.py "질문"                   # 터미널에서 질문
python eval.py --check                  # 채점기 점검 (무료)
python eval.py --model claude-haiku-5-5 # 평가 실행
uvicorn app:app --reload                # http://127.0.0.1:8000
```

## 한계

- 채점이 "정답 값이 답변에 들어 있는가"만 보므로, 다른 기준의 숫자를 앞세우고 정답을 뒤에 덧붙인 답도 통과함
- 평가 문항이 이 데이터 기준으로는 쉬워 Opus·Haiku 간 차이가 드러나지 않음 → 다중 턴 질문, 정제되지 않은 데이터 문항 필요
- 모든 결과는 1회 실행 기준

데이터는 모두 Python으로 생성한 가상 데이터임.
