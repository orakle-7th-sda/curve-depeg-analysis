# DEX는 CEX보다 스테이블코인 디페그를 먼저 감지할 수 있다

**On-Chain Before Off-Chain: Curve 3Pool as an Early Stablecoin Depeg Indicator**

**Author:** KAIST Blockchain Research Society Orakle — 7th ODA Team

**기준 시점:** 2026년 3월

---

> **Disclaimer**
>
> 본 문서는 정보 제공 목적으로만 작성되었으며, 투자 권유 또는 금융 자문이 아닙니다. 스테이블코인 및 DeFi 프로토콜에 대한 참여는 디페그 리스크, 스마트 컨트랙트 취약점, 유동성 리스크, 규제 불확실성 등 상당한 위험을 수반합니다. 어떠한 결정도 독립적인 조사와 전문가 상담을 거쳐 본인의 판단 하에 이루어져야 합니다.
>
> **데이터 정확성:** 본 문서의 수치 및 선행성 분석은 Nansen, Kaiko, Xenophon Labs 등 외부 연구 기반이며, 해당 시점의 추정값입니다. 최신 데이터는 각 출처에서 직접 확인하십시오.
>
> **외부 링크 주의:** 본 문서의 링크는 작성 시점 기준으로 검증되었으나, 이후 도메인 변경·만료 등이 발생할 수 있습니다. 접속 전 URL을 반드시 확인하십시오.

---

스테이블코인 디페그 상황에서 Curve 3Pool의 풀 비율 변화는 중앙화 거래소(CEX)의 가격 이탈보다 먼저 나타난다. 아래 세 가지 독립적 실증 사례가 이를 뒷받침한다.

단, 이 선행성은 디페그 국면에 한정된다. 평상시 일반적인 가격 발견에서는 CEX가 선도하고 DEX가 따라가는 패턴이 일반적이다 (Journal of Futures Markets, 2025). 디페그 국면에서 DEX가 앞서는 이유는 구조적이다 — 마찰 없는 접근, 24시간 봇 감시, 대형 포지션의 자연스러운 경로라는 세 가지 속성 때문에 위기 시 대량 매도 흐름이 CEX보다 Curve로 먼저 유입된다.

---

## 1. 왜 DEX 풀이 CEX 가격보다 먼저 반응하는가

스테이블코인에 문제가 발생할 때 시장 참여자들은 "문제 있는 코인을 팔고 안전한 코인으로 대피"하는 행동을 한다. 이 행동이 어디서 먼저 일어나는지가 선행성을 결정한다.

DeFi 참여자들이 CEX 오더북보다 Curve 3Pool로 먼저 이동하는 이유는 세 가지다.

1. **마찰 없는 접근** — Curve에는 출금 제한, KYC, 로그인이 없다. 지갑 연결만으로 즉시 스왑이 체결된다. CEX는 계정 인증, 출금 한도, 거래 중단 가능성이 있는 반면 Curve 컨트랙트는 누구도 거래를 막을 수 없다.
2. **24시간 차익거래 봇** — MEV 봇들이 Curve 풀을 블록 단위로 감시한다. Curve 3Pool에서 MEV 거래가 전체 거래량의 약 20%를 차지한다는 분석이 있을 만큼, 가격 불균형이 생기면 즉각적으로 스왑이 들어온다.
3. **대규모 포지션의 자연스러운 경로** — 위기 시 기관급 참여자들은 CEX의 제약 없이 즉시 대규모 스테이블코인을 교환할 수 있는 Curve를 먼저 이용한다. $1M 이상 규모에서도 슬리피지가 0.04% 수준에 불과해 대형 거래에 최적화되어 있다.

> **참고**: 이 세 가지 구조적 이유는 아래 섹션 2~4의 실증 사례에서 반복적으로 확인된다. Kaiko는 *"Curve was the most liquid market for UST"*로, Nansen은 *"7개의 대형 지갑이 CEX 이전에 Curve를 통해 먼저 스왑했다"*고 분석했다.
> - [Kaiko — DEX Liquidity Pool Data](https://research.kaiko.com/insights/predicting-ust-collapse)
> - [Nansen — On-Chain Forensics](https://www.nansen.ai/research/on-chain-forensics-demystifying-terrausd-de-peg)
> - [Amberdata — Curve Ecosystem Primer](https://blog.amberdata.io/curve-your-enthusiasm-curve-and-the-curve-ecosystem-defi-prime)

결과적으로 Curve 3Pool의 토큰 비율 변화가 CEX 가격 변화보다 먼저 일어난다. 아래 세 사례가 이를 실증한다.

---

## 2. UST 붕괴 (2022년 5월) — 가장 강력한 근거

### 무슨 일이 있었나

2022년 5월 Terra 생태계의 알고리즘 스테이블코인 UST가 붕괴했다. $400억 규모의 생태계가 수일 만에 붕괴하며 암호화폐 역사상 최대 규모의 스테이블코인 디페그 사태로 기록됐다.

### 누가, 어디서, 무슨 거래를 했나

Nansen의 온체인 포렌식 분석에 따르면 7개의 대형 지갑이 다음 순서로 행동했다.

1. Anchor Protocol에서 대량의 UST 인출 (5월 7~8일)
2. Wormhole 브릿지를 통해 UST를 Terra 체인에서 이더리움으로 이동
3. Curve의 **UST/3CRV 메타풀**에서 UST → USDC 대규모 스왑 (5월 7~8일)
4. 이후 CEX로 UST 전송 및 매도 (5월 9~10일)

### DEX가 CEX보다 먼저였다

Nansen은 다음과 같이 결론지었다.

> *"UST swapping vs other stablecoins in the Curve liquidity pools **predated** exchange selling. Net UST inflows to centralized exchanges gathered momentum on May 9, 2022 and were the largest on May 10. If the net selling to CEXs likely dealt the last blow to the de-pegging process, it seemed **unlikely to have initiated it**."*
>
> — [On-Chain Forensics: Demystifying TerraUSD De-peg, Nansen](https://www.nansen.ai/research/on-chain-forensics-demystifying-terrausd-de-peg)

Kaiko의 분석도 동일한 결론이다.

> *"Using liquidity pool data, Kaiko showed how there was a **two-day lag** in market activity on DEXs that could have predicted the liquidity crisis that overflowed to CEXs."*
>
> — [Predicting the UST Collapse with DEX Liquidity Pool Data, Kaiko](https://research.kaiko.com/insights/predicting-ust-collapse)

**Curve 풀 불균형(5월 7~8일) → CEX 대규모 매도(5월 9~10일): 약 2일 선행.**

### 이 사례의 특징

UST 붕괴는 **의도적 공격 + 연쇄 패닉** 복합형이다. 핵심은 DEX(Curve) 활동이 CEX 활동을 명확히 선행했다는 점이며, 이것이 Nansen과 Kaiko 두 독립 기관에 의해 검증됐다.

---

## 3. SVB 사태 (2023년 3월) — 외부 충격형

### 무슨 일이 있었나

2023년 3월 Silicon Valley Bank(SVB) 파산으로 USDC 발행사인 Circle이 SVB에 $33억을 예치하고 있다는 사실이 알려졌다. USDC의 달러 담보 일부가 묶일 수 있다는 우려에 시장은 USDC를 내다 팔기 시작했다.

### 누가, 어디서, 무슨 거래를 했나

SVB 보도에 반응한 DeFi 참여자들이 Curve 3Pool을 통해 USDC → DAI/USDT 스왑을 집중 실행했다. 단일 주체가 아닌 시장 전체의 탈출 흐름이 Curve를 경유했다. 풀에서 USDC가 빠르게 소진되면서 3Pool 내 USDC 비중이 급격히 감소했고, 반대로 DAI와 USDT 비중이 높아졌다.

### Curve가 CEX보다 5시간 먼저 이상을 감지했다

Xenophon Labs의 BOCD(Bayesian Online Changepoint Detection) 모델은 Curve 3Pool 지표를 기반으로 **March 10일 21:00 UTC**에 디페그 경보를 발령했다. Chainlink 가격 오라클(CEX 기반)이 USDC $0.99 이하를 기록한 것은 **March 11일 02:00 UTC**였다.

**Curve 3Pool 신호 → Chainlink(CEX 기반 오라클) 이탈: 5시간 선행.**

> **출처**: [CurveMetrics — Xenophon Labs](https://xenophonlabs.substack.com/p/curvemetrics)

### 이 사례의 특징

SVB 사태는 **외부 충격형** 디페그다. 뉴스(3월 9~10일)가 먼저 발생했고, Curve 신호는 그 뒤를 따랐다. 따라서 Curve 풀 상태는 CEX 가격 이탈보다 앞섰지만, 뉴스 자체보다 먼저는 아니었다. 이 경우 온체인 모니터링만으로 디페그를 '최초' 감지하는 것은 불가능하다.

---

## 4. USDT 하방 이탈 (2023년 6월) — 온체인 고래형

### 무슨 일이 있었나

2023년 6월 15일 USDT가 $0.996까지 하락했다. 뉴스나 외부 사건이 없었다. 원인은 단일 대형 온체인 거래였다.

### 누가, 어디서, 무슨 거래를 했나

1. **CZSamSun.eth** 주소가 Aave v2에 약 17,000 ETH + 14,000 stETH를 담보로 예치했다.
2. USDT **$3,150만**을 차입했다.
3. 차입한 USDT를 1inch 어그리게이터를 통해 USDC로 스왑했다.
4. 이 매도 물량이 Curve 3Pool을 통과하며 USDT 비중을 정상(33.3%)에서 **73.79%**까지 끌어올렸다.

USDT를 파는 압력이 풀에 그대로 반영됐고, 이후 CEX 가격이 반응했다.

| 시각 | 이벤트 | Curve 3Pool USDT 비중 | CEX USDT 가격 |
|------|--------|----------------------|--------------|
| 이전 | 정상 상태 | **33.3%** | $1.000 |
| 거래 직후 | CZSamSun.eth 스왑 체결 | **73.79%** | $1.000 (미반응) |
| 이후 | 시장 반응 확산 | 불균형 유지 | **$0.996** |

온체인 트랜잭션은 발생 즉시 블록에 기록되어 누구나 확인 가능했다. CEX 가격은 시장 참여자들이 이를 인지하고 반응한 이후에야 변동했다.

> **출처**: [Tether wobbles as Curve 3Pool becomes imbalanced — The Block](https://www.theblock.co/post/234822/tether-depeg-curve-3pool)

### 이 사례의 특징

USDT 하방 이탈은 **온체인 고래형** 디페그다. 단일 대형 거래가 시작점이었다. 이 경우 뉴스가 없으므로 Curve 풀 상태가 사실상 유일한 조기 신호였다. CEX와의 정확한 시간 격차는 공개 출처에서 확인되지 않지만, 구조상 온체인 트랜잭션이 CEX 반응보다 먼저 발생한다.

---

## 5. Curve만 선행하는가 — 다른 DEX와의 비교

Curve만 선행성을 보이는 것은 아니다. Fed(연방준비제도) 연구에 따르면 SVB 사태 당시 DEX 전체의 거래량이 CEX를 크게 초과했다.

> *"During the crisis, trading on DEXs rose dramatically and **accounted for most of the activity**."*
>
> — [Federal Reserve FEDS Note, 2025년 12월](https://www.federalreserve.gov/econres/notes/feds-notes/in-the-shadow-of-bank-run-lessons-from-the-silicon-valley-bank-failure-and-its-impact-on-stablecoins-20251217.html)

단, 이 연구는 거래량 집중을 보여줄 뿐, DEX가 가격 발견에서 CEX를 선행했다는 직접적 주장은 하지 않는다.

그럼에도 **스테이블코인 디페그 모니터링에서 Curve 3Pool이 가장 신뢰도 높은 지표**인 이유는 다음과 같다.

| 비교 항목 | Curve 3Pool | Uniswap V3 |
|-----------|------------|------------|
| 스테이블코인 특화 | ✅ (StableSwap 곡선, A=2000) | ❌ (범용 AMM) |
| 슬리피지 | 매우 낮음 (0.04%) | 상대적으로 높음 |
| TVL 집중도 | 스테이블코인 중 최대 | 분산됨 |
| 신호 관찰 용이성 | 단일 풀 3종 비율 | 풀 분산으로 해석 복잡 |

BIS(국제결제은행) 연구는 스테이블코인 런 상황에서 시장 참여자들이 공개적으로 관측 가능한 정보를 바탕으로 행동을 조율한다고 분석한다. 가장 유동성이 높고 투명한 단일 장소에 탈출 흐름이 집중되는 구조다. Curve 3Pool이 그 역할을 한다.

> **출처**: [BIS Working Paper No. 1164 — "Public Information and Stablecoin Runs"](https://www.bis.org/publ/work1164.pdf) — Ahmed, Aldasoro, Duley

Xenophon Labs는 이 구조적 특성을 실증적으로 검증했다. BOCD 모델을 Curve 3Pool에 적용한 결과, USDC 디페그를 가격 이탈 5시간 전에 선행 감지했다. 핵심 지표는 Shannon Entropy(풀 내 토큰 분포 균등도)와 Net Swap Flow(방향성 스왑 흐름)였다.

> **출처**: Xenophon Labs CurveMetrics
> - [CurveMetrics 개요 (Substack)](https://xenophonlabs.substack.com/p/curvemetrics)
> - [GitHub: curve-lp-metrics](https://github.com/xenophonlabs/curve-lp-metrics)
> - [Curve Governance 그랜트 제안](https://gov.curve.fi/t/curvemetrics-detecting-token-depegs-on-stableswap-pools/9343)

Curve가 모든 DEX 중 반드시 가장 빠르다는 보장은 없다. 하지만 신호의 신뢰성과 해석 가능성 측면에서 스테이블코인 디페그 조기 감지 지표로 가장 적합하다.

---

## 6. 한계 — 온체인 모니터링으로 잡을 수 없는 경우

세 사례 모두에서 Curve 3Pool은 **CEX 가격보다 먼저** 이상 신호를 냈다. 이 패턴은 일관적이다.

| 항목 | UST 붕괴 (온체인 공격형) | SVB (외부 충격형) | USDT (온체인 고래형) |
|------|-------------------------|-----------------|---------------------|
| 최초 신호 | Curve 풀 (온체인) | 뉴스 (외부) | Curve 풀 (온체인) |
| Curve vs CEX 선행 | **약 2일 앞섬** | **약 5시간 앞섬** | 구조상 온체인이 선행 |
| 온체인만으로 조기 포착 | 완전히 가능 | 부분적 | 완전히 가능 |

단, 한 가지 한계가 있다. **외부 충격형(SVB)에서는 뉴스가 Curve 풀보다 먼저였다.** Curve는 CEX 가격보다 5시간 앞섰지만, 뉴스 보도(3월 9일)보다는 늦었다. 온체인 모니터링만으로는 뉴스를 먼저 감지할 수 없다.

이는 DEX vs CEX의 문제가 아니라, 온체인 데이터 vs 오프체인 정보(뉴스)의 한계다. 온체인 고래형이나 프로토콜 공격형처럼 디페그의 원인 자체가 온체인에서 발생하는 경우에는 이 한계가 적용되지 않는다.

**비교 맥락**: 평상시 일반적인 가격 발견에서는 Uniswap 같은 DEX가 CEX보다 느리다. CEX에서 가격이 움직이면 차익거래자가 DEX로 넘어와 가격을 맞추는 방식이 일반적이다. 디페그 국면에서 패턴이 역전되는 것은 이 세 가지 구조적 이유 때문이다 — 마찰 없는 접근, MEV 봇의 즉각 반응, 대형 포지션의 Curve 경유.

> **출처**: [Price Discovery and Efficiency in Uniswap Liquidity Pools — Journal of Futures Markets (2025)](https://onlinelibrary.wiley.com/doi/10.1002/fut.22593)

---

## 결론

세 사례 모두에서 Curve 3Pool의 토큰 비율 변화는 CEX 가격 이탈보다 먼저 나타났다. Nansen과 Kaiko의 분석은 UST 붕괴에서 DEX 활동이 CEX 매도를 2일 선행했음을 실증했고, Xenophon Labs는 SVB 사례에서 Curve 3Pool 지표가 CEX 기반 가격 오라클을 5시간 앞섰음을 보였다.

이 선행성은 가격 지표가 아닌 온체인 풀 비율 지표 기준으로, 그리고 디페그 스트레스 국면에서 성립한다. 이 구조적 특성을 실시간으로 포착하는 것이 본 프로젝트의 핵심 가설이다.

---

_최종 업데이트: 2026년 3월_
