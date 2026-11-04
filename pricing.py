"""토큰 → 비용 계산 (평가·서버 로그가 같이 씀)"""

# 100만 토큰당 달러 (입력, 출력, 캐시 읽기). 캐시 쓰기는 입력의 1.25배
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
KRW_PER_USD = 1400  # 대략적인 환율 (원 환산 참고용)


def cost_usd(model, usage):
    p_in, p_out, p_read = PRICES.get(model, (0, 0, 0))
    return (usage["input_tokens"] * p_in + usage["output_tokens"] * p_out
            + usage.get("cache_read_input_tokens", 0) * p_read
            + usage.get("cache_creation_input_tokens", 0) * p_in * 1.25) / 1e6
