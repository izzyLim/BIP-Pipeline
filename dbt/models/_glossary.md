{#
    BIP 도메인 용어집 (dbt doc blocks)

    이 파일의 정의는 `dbt docs generate` 시 자동으로 사이트에 표시되며,
    모델 yml에서 `{{ doc('term_name') }}` 으로 재사용 가능하다.

    BIP OpenMetadata Glossary(77개 용어)에 대응하는 dbt 버전 — 변환 모델과
    같은 저장소에 위치하므로 PR 단위로 함께 변경된다.
#}


{# ========== 데이터 모델링 개념 ========== #}

{% docs grain %}
**Grain (입도)**

테이블의 한 행이 무엇을 나타내는지 정의하는 개념. NL2SQL 친화적 모델 설계의 첫걸음.

| Grain 예시 | 의미 |
|----------|------|
| `종목×일자` | 한 종목의 하루치 시세·수급 |
| `종목×연도` | 한 종목의 1년 재무 실적 |
| `날짜` | 그날 하루의 매크로 지표 (환율·금리) |

**왜 중요한가:** Grain이 다른 테이블을 직접 JOIN하면 중복·누락 발생. 같은 Grain끼리만 안전하게 JOIN 가능.
{% enddocs %}


{% docs gold_table %}
**Gold Table**

Raw 테이블을 pre-join + 단위 통일 + 계산까지 마친 NL2SQL 친화적 와이드 테이블.

- LLM이 단일 SELECT만 하면 되도록 설계
- 단위는 모두 통일 (금액=원, 비율=%)
- 자주 사용되는 파생 지표는 컬럼으로 미리 계산

BIP의 `analytics_*` 테이블이 여기에 해당.
{% enddocs %}


{% docs curated_view %}
**Curated View**

Gold Table 위에 **비즈니스 규칙을 SQL로 고정한** View. 주로 Boolean Flag 또는 해석 컬럼 추가.

목적: LLM이 "저평가주" 같은 추상 개념을 매번 새로 계산하지 않고, **단순 필터링만** 하도록.
{% enddocs %}


{% docs boolean_flag %}
**Boolean Flag**

비즈니스 정의를 `true/false` 컬럼으로 박아둔 패턴.

```sql
(per_actual < 10 AND pbr_actual < 1) AS is_value_stock
```

**왜 필요한가:** "저평가주 찾아줘" 라는 질문에 LLM이 `WHERE PER<10 AND PBR<1` 을 스스로 만들어야 하는데, 기준이 매번 다를 위험. Boolean으로 고정하면 정의 일관성 보장.

BIP 검증: 사용률 0% → 87%로 향상.
{% enddocs %}


{% docs interpretation_column %}
**해석 컬럼 (Interpretation Column)**

숫자 컬럼의 의미를 텍스트로 변환한 컬럼.

```sql
CASE
    WHEN foreign_buy_volume > 0 THEN '순매수'
    WHEN foreign_buy_volume < 0 THEN '순매도'
END AS foreign_direction
```

**왜 필요한가:** LLM이 결과만 보고 답변을 생성할 때 숫자 의미를 오해할 수 있음 (음수 = 이상치라고 판단). 데이터에 직접 텍스트를 박아넣어 환각 방지.
{% enddocs %}


{# ========== 밸류에이션 지표 ========== #}

{% docs per %}
**PER (Price Earnings Ratio, 주가수익비율)**

`시가총액 / 당기순이익` — 회사가 1원을 벌 때 시장이 매기는 가치 배수.

| 값 | 해석 |
|----|------|
| < 10 | 저평가 가능성 (단, 적자/성장정체 가능성도 봐야 함) |
| 10~20 | 일반적 범위 |
| > 30 | 성장 기대 또는 고평가 |

음수가 나오면 적자 기업 — 일반적으로 PER 산출에서 제외.
{% enddocs %}


{% docs pbr %}
**PBR (Price Book-value Ratio, 주가순자산비율)**

`시가총액 / 자기자본` — 회사 순자산 대비 주가 배수.

| 값 | 해석 |
|----|------|
| < 1 | 청산 가치 미만 — 저평가 가능성 또는 사양 산업 |
| 1~2 | 일반적 범위 |
| > 3 | 무형 자산이 많은 성장 산업 (IT/바이오) |
{% enddocs %}


{% docs roe %}
**ROE (Return On Equity, 자기자본이익률)**

`당기순이익 / 자기자본 × 100 (%)` — 회사가 자본을 얼마나 효율적으로 굴리는지.

| 값 | 해석 |
|----|------|
| ≥ 15% | 우량 (워런 버핏 기준선) |
| 10~15% | 양호 |
| < 5% | 비효율 또는 적자 |

부채로 ROE를 부풀리는 케이스가 있어 `debt_ratio`와 함께 봐야 함.
{% enddocs %}


{% docs debt_ratio %}
**부채비율 (Debt Ratio)**

`총부채 / 자기자본 × 100 (%)` — 자본 대비 부채 비중.

| 값 | 해석 |
|----|------|
| < 100% | 안전 |
| 100~200% | 보통 |
| > 200% | 과다 (금융업 제외) |
{% enddocs %}


{# ========== 비즈니스 분류 ========== #}

{% docs value_stock %}
**저평가주 (Value Stock)**

가치 대비 주가가 낮게 형성된 종목. BIP 정의:

- PER < 10 (이익 대비 주가가 10배 미만)
- AND PBR < 1 (순자산 대비 주가가 1배 미만)
- AND 두 지표 모두 양수 (적자 기업 제외)

워런 버핏·벤저민 그레이엄식 가치투자 종목 후보.

**주의:** "저평가"가 항상 좋은 것은 아님 — 사양 산업이라 시장이 외면 중일 수도 있다.
{% enddocs %}


{% docs high_roe %}
**고ROE 종목**

자기자본이익률이 15% 이상인 종목. 자본을 효율적으로 운용하는 우량 기업의 지표.

**왜 15% 기준인가:** 워런 버핏이 "장기 보유 후보는 ROE 15% 이상" 으로 제시한 임계값.
{% enddocs %}


{% docs quality_stock %}
**우량주 (Quality Stock)**

저평가 + 고ROE를 동시에 만족하는 이상적 종목. BIP 정의:

- PER < 15 (이익 대비 합리적)
- AND PBR < 1.5 (자산 대비 합리적)
- AND ROE ≥ 10% (자본 효율 양호)

"싸면서도 잘 굴러가는 회사" — 가치투자 + 퀄리티 투자 교집합.
{% enddocs %}


{% docs high_debt %}
**부채과다 종목**

부채비율 200% 초과. 금융 위기 시 취약하므로 일반 산업에서는 회피 대상.

**예외:** 금융업/리스업은 부채가 사업 모델 자체이므로 별도 기준 적용.
{% enddocs %}


{# ========== 수급 (Flow) ========== #}

{% docs foreign_direction %}
**외국인 수급 방향 (Foreign Direction)**

외국인 투자자의 순매수/순매도 방향을 텍스트로 표현한 해석 컬럼.

| 값 | 의미 |
|----|------|
| `순매수` | foreign_buy_volume > 0 (외국인 매수 우세) |
| `순매도` | foreign_buy_volume < 0 (외국인 매도 우세) |
| `보합` | foreign_buy_volume = 0 |
| `데이터없음` | foreign_buy_volume IS NULL |

LLM이 답변 생성 시 "외국인 -20,778 = 이상치" 로 오해하지 않도록 만든 [해석 컬럼](#interpretation_column).
{% enddocs %}


{% docs change_label %}
**등락 라벨 (Change Label)**

전일 대비 등락률을 5단계 텍스트로 표현한 해석 컬럼.

| 라벨 | 등락률 |
|------|--------|
| `강한 상승` | ≥ +3% |
| `상승` | +1% ~ +3% |
| `보합` | -1% ~ +1% |
| `하락` | -3% ~ -1% |
| `강한 하락` | ≤ -3% |
| `데이터없음` | NULL |
{% enddocs %}


{# ========== 기간/시점 ========== #}

{% docs trade_date %}
**거래일 (trade_date)**

해당 종목의 시장 거래일 (KST 기준). 주말/공휴일은 데이터 없음.

미국 주식은 `timestamp_ny` 기준 거래일 — 한국 주식의 `trade_date`와 하루 차이 가능.
{% enddocs %}


{% docs fiscal_year %}
**회계연도 (fiscal_year)**

DART 사업보고서 기준 연도. 대부분 12월 결산이지만 일부 기업은 3/6/9월 결산.

`report_type='annual'` 인 행이 그 해의 확정 실적.
{% enddocs %}
