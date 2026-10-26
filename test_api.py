import os

import anthropic
from dotenv import load_dotenv

# .env 파일의 ANTHROPIC_API_KEY 를 환경변수로 불러옴
load_dotenv()

key = os.getenv("ANTHROPIC_API_KEY")
if not key:
    raise SystemExit(".env 파일에 ANTHROPIC_API_KEY 가 없습니다")
print("키 확인:", key[:10] + "..." + key[-4:])  # 앞뒤 일부만 표시

client = anthropic.Anthropic()  # 키는 환경변수에서 자동으로 읽음
response = client.messages.create(
    model="claude-haiku-5-5",  # 연결 확인용이라 가장 저렴한 모델
    max_tokens=100,
    messages=[{"role": "user", "content": "한 문장으로 자기소개 해줘"}],
)
print("응답:", response.content[0].text)
print("사용 토큰:", response.usage.input_tokens, "입력 /", response.usage.output_tokens, "출력")
