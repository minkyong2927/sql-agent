# 어느 컴퓨터·클라우드에서나 같은 환경으로 실행하기 위한 이미지
FROM python:3.14-slim

# 파이썬 출력이 바로 로그에 찍히게, .pyc 파일은 만들지 않게
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8

WORKDIR /app

# 패키지 먼저 설치: 코드만 바뀌면 이 단계는 캐시를 재사용해 빌드가 빨라짐
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 가상 데이터 DB를 이미지 안에 미리 만들어 둠 (실행 중에는 읽기 전용으로만 씀)
RUN python schema.py && python seed.py

# 관리자 권한이 아닌 일반 사용자로 실행
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
# 클라우드가 PORT 환경변수를 주면 그 포트, 없으면 8000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
