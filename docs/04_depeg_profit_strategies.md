# 디페그 감지 이후: Curve 데이터 기반 수익 전략

**After Detection: Backtested Profit Strategies Using Curve 3Pool On-Chain Data**

**Author:** KAIST Blockchain Research Society Orakle — 7th ODA Team

**기준 시점:** 2026년 3월

---

> **Disclaimer**
>
> 본 문서는 정보 제공 목적으로만 작성되었으며, 투자 권유 또는 금융 자문이 아닙니다. 스테이블코인 및 DeFi 프로토콜에 대한 참여는 디페그 리스크, 스마트 컨트랙트 취약점, 유동성 리스크, 규제 불확실성 등 상당한 위험을 수반합니다. 어떠한 결정도 독립적인 조사와 전문가 상담을 거쳐 본인의 판단 하에 이루어져야 합니다.
>
> **데이터 정확성:** 본 문서의 백테스팅 수치는 Dune Analytics 실측 스왑 데이터(VWAP) 기반이며, 실제 거래 체결가와 차이가 있을 수 있습니다. 과거 수익률은 미래 결과를 보장하지 않습니다.

---

앞선 분석([02_curve_as_depeg_early_indicator.md](02_curve_as_depeg_early_indicator.md))에서 Curve 3Pool의 풀 구성 변화가 CEX 가격 이탈보다 먼저 나타난다는 것을 확인했다. 이 문서는 그 신호를 포착했을 때 실제로 어떤 행동을 취할 수 있는지를 다룬다.

실제 온체인 데이터(Dune Analytics)를 기반으로 SVB 사태(2023.03)와 USDT 하방 이탈(2023.06) 두 사례에서 두 가지 전략을 백테스팅했다.

---

## 1. 데이터

Dune Analytics의 `dex.trades` 테이블에서 Curve 3Pool 컨트랙트(`0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7`)의 실제 스왑 기록을 시간별로 집계했다.

```sql
SELECT
    date_trunc('hour', block_time) AS hour,
    token_bought_symbol,
    token_sold_symbol,
    SUM(token_bought_amount) AS bought_amount,
    SUM(token_sold_amount)   AS sold_amount,
    COUNT(*)                 AS trade_count
FROM dex.trades
WHERE project_contract_address = 0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7
  AND block_time BETWEEN ...
GROUP BY 1, 2, 3
```

각 이벤트의 데이터 범위와 풀 상태:

| 사태 | 기간 | 디페그 대상 | 풀 최대 비중 | 최저 체결가 |
|------|------|------------|------------|------------|
| SVB | 2023-03-09 ~ 03-14 | USDC | **44.0%** | $0.8849 |
| USDT 하방 이탈 | 2023-06-14 ~ 06-16 | USDT | **63.4%** | $0.9966 |

풀 구성은 이벤트 직전 실제 잔고에서 시작해 시간별 스왑 플로우를 누적 적용해 재현했다 ([`src/scripts/backtest_historical.py`](../../src/scripts/backtest_historical.py) — `reconstruct_pool_composition()`).

```python
# Update pool reserves for each swap that occurred
for _, row in hour_df.iterrows():
    t_in  = row["token_sold_symbol"]    # token entering the pool → reserve increases
    t_out = row["token_bought_symbol"]  # token leaving the pool → reserve decreases
    reserves[t_in]  += row["sold_amount"]
    reserves[t_out] -= row["bought_amount"]

# Compute hourly share ratios
total = sum(reserves.values())
usdc_pct = reserves["USDC"] / total * 100  # this value is used to evaluate thresholds
```

---

## 2. 두 가지 전략

### 전략 ①: AMM 역방향 스왑

디페그가 최고조에 달한 시점에 Curve 3Pool에 직접 진입한다. 디페그된 토큰이 풀에 과잉 공급된 상태이므로, 반대편 토큰을 넣으면 할인된 가격에 디페그 토큰을 받을 수 있다.

**실행 흐름:**
1. Curve 3Pool에서 풀 비중 피크 시점 확인
2. 안전한 스테이블코인을 넣고 디페그된 토큰을 꺼냄
3. 디페그 토큰이 $1.00로 회복하면 매도

어그리게이터 없이 Curve 3Pool 단일 풀만 사용한다. 별도 담보나 차입 없이 본인 자산으로 스왑하는 가장 단순한 구조다.

```python
# Find the hour of maximum pool imbalance (peak)
peak_hour  = composition_df.loc[composition_df["usdc_pct"].idxmax(), "hour"]

# Effective fill price at peak (VWAP)
entry_price = _get_price_at(price_df, peak_hour)  # e.g. $0.9391

# Return: buy at entry price, sell at $1.00 after recovery
gross_pnl_pct = (1.00 - entry_price) / entry_price * 100  # → +6.49%
```

---

### 전략 ②: 선취 포지션

Curve 3Pool의 풀 비중이 특정 **임계치(threshold)** 를 넘는 순간을 신호로 삼아, 가격이 충분히 반응하기 전에 먼저 포지션을 잡는다.

**실행 흐름:**
1. Curve 3Pool 모니터링 — 디페그 토큰 비중이 임계치 초과 시 진입
2. ETH를 Aave에 담보로 맡기고 안전한 스테이블코인을 인출
3. 그 자금으로 디페그된 토큰을 Curve에서 매수
4. 토큰이 $1.00로 회복되면 매도 → Aave 상환 → 차익 보유

> SVB: ETH 담보 → USDT 인출 → 싼 USDC 매수
> USDT 하방 이탈: ETH 담보 → USDC 인출 → 싼 USDT 매수

전략 ①과 달리 **신호를 보고 미리 진입**한다는 점이 핵심이다. 가격이 더 빠지기 전에 더 싸게 살 수 있지만, 실제로 디페그가 심화되지 않으면 이자 비용만 발생할 수 있다.

```python
# Use the first hour the threshold is crossed as the entry signal
signal_rows = composition_df[composition_df["usdc_pct"] >= threshold]
entry_hour  = signal_rows.iloc[0]["hour"]
entry_price = _get_price_at(price_df, entry_hour)

# Aave borrowing cost (60% APR applied during crisis period)
apr             = 0.60 if entry_pct >= 65 else 0.05
borrow_cost_pct = apr / 365 / 24 * holding_hours * 100

net_pnl_pct = (1.0 - entry_price) / entry_price * 100 - borrow_cost_pct
```

---

## 3. 임계치란 무엇인가

Curve 3Pool은 DAI, USDC, USDT 세 토큰이 들어 있다. 정상 상태에서는 세 토큰이 균등하게 각각 약 33%씩 구성된다.

디페그가 시작되면 사람들이 문제 있는 토큰을 풀에 팔기 시작하면서 그 토큰의 비중이 33%를 넘어 상승한다. **임계치는 이 비중이 몇 %를 넘을 때 포지션에 진입할 것인가를 결정하는 기준값**이다.

```
정상:  DAI 33% / USDC 33% / USDT 33%

SVB 진행 중:
  threshold 33% → DAI 40.7% / USDC 33.4% / USDT 26.0%  (USDC가 막 오르기 시작)
  threshold 38% → DAI 35.4% / USDC 39.0% / USDT 25.7%  (USDC가 더 쌓임)
  threshold 42% → DAI 31.1% / USDC 42.9% / USDT 26.0%  (피크 근처)
```

임계치가 낮을수록 더 일찍 진입 → 가격이 아직 충분히 빠지지 않아 수익이 작거나, 디페그가 실제로 발생하지 않을 위험(위양성)이 있다. 임계치가 높을수록 확신이 높은 상태에서 진입 → 이미 가격이 많이 빠진 뒤라 수익이 작아질 수 있다.

---

## 4. 백테스팅 결과

백테스팅 로직: [`src/scripts/backtest_historical.py`](../../src/scripts/backtest_historical.py)
유효 실행가 계산: 실제 스왑 데이터의 시간별 VWAP(`sold_amount / bought_amount`)
수익 계산: 진입가에서 매수 → $1.00 회복 시 매도 (전략 ②는 Aave 이자 차감)

---

### SVB 사태 (2023.03) — USDC 디페그

**전략 ①: 피크 시점 단일 진입**

| 풀 구성 (진입 시점) | 체결가 | 수령량 | 보유 | 순수익 |
|-------------------|--------|--------|------|--------|
| DAI 30.8% / USDC 44.0% / USDT 25.2% | $0.9391 | 53,245 USDC | 4시간 | **+6.49%** |

**전략 ②: 임계치별 선취 포지션** (ETH 담보 → USDT 인출 → 싼 USDC 매수)

| 임계치 | 풀 구성 (진입 시점) | 체결가 | 보유 | 순수익 |
|--------|-------------------|--------|------|--------|
| 33% | DAI 40.7% / USDC 33.4% / USDT 26.0% | $0.9392 | 1h | +6.47% |
| 35% | DAI 38.7% / USDC 35.6% / USDT 25.7% | $0.9121 | 1h | +9.63% |
| **38%** | **DAI 35.4% / USDC 39.0% / USDT 25.7%** | **$0.8849** | **1h** | **+13.01%** |
| 40% | DAI 32.4% / USDC 41.8% / USDT 25.9% | $0.9012 | 15h | +10.95% |
| 42% | DAI 31.1% / USDC 42.9% / USDT 26.0% | $0.9130 | 14h | +9.53% |

SVB에서는 선취 포지션이 역방향 스왑보다 2배 이상 수익이 났다. USDC 가격이 먼저 급락하고 풀 불균형이 뒤따른 구조였기 때문에, 38% 임계치에서의 진입이 최저가($0.8849)를 포착했다. 이자 비용은 1시간 보유로 사실상 0 수준이다.

USDT 비중이 25~26%로 일정한 반면 DAI 비중이 40%→31%로 감소한 점이 눈에 띈다. USDC 탈출 수요가 USDT뿐 아니라 DAI 방향으로도 분산됐다는 뜻이다.

---

### USDT 하방 이탈 (2023.06) — USDT 디페그

**전략 ①: 피크 시점 단일 진입**

| 풀 구성 (진입 시점) | 체결가 | 수령량 | 보유 | 순수익 |
|-------------------|--------|--------|------|--------|
| DAI 18.9% / USDC 17.7% / USDT 63.4% | $0.9981 | 50,096 USDT | 42시간 | **+0.19%** |

**전략 ②: 임계치별 선취 포지션** (ETH 담보 → USDC 인출 → 싼 USDT 매수)

| 임계치 | 풀 구성 (진입 시점) | 체결가 | 보유 | 순수익 |
|--------|-------------------|--------|------|--------|
| 45% | DAI 28.8% / USDC 26.0% / USDT 45.2% | $0.9999 | 48h | **-0.02%** |
| 50% | DAI 27.2% / USDC 22.0% / USDT 50.9% | $0.9997 | 45h | +0.01% |
| 55% | DAI 23.6% / USDC 20.7% / USDT 55.7% | $0.9994 | 43h | +0.04% |
| **60%** | **DAI 18.9% / USDC 17.7% / USDT 63.4%** | **$0.9981** | **42h** | **+0.17%** |

USDT 하방 이탈은 전체 디페그 폭이 $0.004에 불과했다. 선취 포지션이 SVB와 반대로 작동했는데 — 일찍 진입할수록 오히려 손해다. 45% 임계치에서 진입하면 이자 비용(-0.02%)이 수익을 초과한다. 피크(60%) 근처에서 진입해야 실질적으로 유의미한 수익이 난다.

DAI와 USDC가 28%→18%로 고르게 줄어들면서 USDT만 집중적으로 쌓인 구조는 단일 주체(CZSamSun.eth의 대규모 스왑)에 의한 압력을 반영한다.

---

## 5. 두 전략, 두 사태 비교

| | SVB (USDC) | USDT 하방 이탈 |
|--|--|--|
| 디페그 폭 | $0.1151 (11.5%) | $0.0034 (0.34%) |
| 전략 ① 수익 | +6.49% | +0.19% |
| 전략 ② 최고 수익 | **+13.01%** | +0.17% |
| 최적 임계치 | 38% | 60% (피크) |
| 전략 ② vs ① | 선취 포지션 우위 | 두 전략 거의 동일 |
| 조기 진입 위험 | 없음 (빠를수록 유리) | 있음 (이자 비용 초과) |

두 사태는 정반대의 패턴을 보였다.

**SVB**는 가격이 먼저 급락하고 풀 불균형이 나중에 쌓이는 구조였다. 일찍 신호를 잡을수록 더 싼 가격에 진입했고, 선취 포지션의 이점이 극대화됐다.

**USDT 하방 이탈**은 단일 대형 거래가 순간적으로 풀을 왜곡시킨 경우다. 가격 변동 자체가 작아 두 전략의 수익 차이가 없고, 선취 진입의 이점도 없다. 이런 소규모 이벤트에서는 이자 비용이 수익을 갉아먹는다.

---

## 결론

Curve 3Pool의 풀 비중 변화는 디페그를 먼저 알려주지만, 그 신호를 어떻게 활용할지는 사태의 성격에 따라 달라진다.

디페그 폭이 크고 가격이 먼저 급락하는 유형(SVB형)에서는 선취 포지션이 유효하다. 신호를 보고 피크 전에 진입할수록 더 좋은 가격을 잡을 수 있고, 짧은 보유 시간 덕에 이자 비용도 무시할 수 있다.

디페그 폭이 작고 단발성 충격에 의한 유형(USDT형)에서는 역방향 스왑이 현실적이다. 선취 포지션은 이자 비용 부담이 크고 수익 여지가 좁다. 오히려 피크 시점을 기다렸다가 단순 스왑하는 것이 낫다.

두 전략 모두 Curve 3Pool 모니터링을 전제로 한다. 풀 비중 변화가 없다면 진입 신호 자체가 없다.

---

_최종 업데이트: 2026년 3월_
