{#
    to_won — 시가총액·금액 단위를 원 단위로 통일

    BIP에서 자주 발생한 함정: 어떤 컬럼은 "억원", 어떤 컬럼은 "원" 단위로
    저장되어 있어 PER 계산 시 0이 나오는 사례 발생.

    이 매크로는 값의 크기로 단위를 추론한다:
      - 1억 미만이면 "억원 단위로 저장됨" 으로 판단 → 1억 곱함
      - 1억 이상이면 "이미 원 단위" 로 판단 → 그대로

    사용법: SELECT {{ to_won('market_value') }} FROM ...
#}

{% macro to_won(column_name, alias=None) %}
    CASE
        WHEN {{ column_name }} IS NULL THEN NULL
        WHEN {{ column_name }} < 100000000 THEN ({{ column_name }} * 100000000)::numeric
        ELSE {{ column_name }}::numeric
    END {% if alias %}AS {{ alias }}{% else %}AS {{ column_name }}_won{% endif %}
{% endmacro %}
