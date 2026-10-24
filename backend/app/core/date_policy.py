"""
MES 날짜 기준 정책 (dev_last_year: 1년 전 기준, production: GETDATE() 기준)
개발 DB 는 최근 데이터가 비운영이고 약 1년 전 구간만 운영과 같은 실데이터
"""
from __future__ import annotations

import os

# dev_last_year 또는 production
MES_DATE_MODE = os.getenv("MES_DATE_MODE", "dev_last_year").strip().lower()

_DEV_LAST_YEAR_RULES = """4. [개발 DB / 벤치마크 모드] 기본 기준일은 **1년 전**이다.
   연결 DB는 개발용이라 최근 시점 데이터는 실제 운영 흐름이 아니며, 약 1년 전 데이터가 운영과 동일한 실데이터이다.
   사용자가 날짜를 별도로 지정하지 않으면 DATEADD(year, -1, GETDATE())를 기준(end)으로 사용하라.
   - "오늘" / 날짜 미지정 → 기준일 = DATEADD(year, -1, GETDATE())
   - "어제" → DATEADD(day, -1, DATEADD(year, -1, CAST(GETDATE() AS date)))
   - "이번 달" → 1년 전 같은 달
   - "이번 주" → 1년 전 기준 해당 주
   - "최근 N일" / 일별 추이(기간 미명시) → TRACKINTIME >= DATEADD(day, -N, DATEADD(year, -1, GETDATE())) AND TRACKINTIME < DATEADD(year, -1, GETDATE())
     (추이 질의에서 N이 없으면 N=30 적용)
5. 특정 연도/월이 명시된 경우 (예: "2025년 12월") → 리터럴 날짜 사용
6. 날짜 범위는 BETWEEN보다 >= AND < 형식"""

_PRODUCTION_RULES = """4. [운영 DB 모드] 사용자가 날짜를 지정하지 않으면 **GETDATE()** 를 기준으로 한다.
   - "오늘" / 날짜 미지정 → GETDATE() 기준
   - "어제" → DATEADD(day, -1, CAST(GETDATE() AS date))
   - "최근 N일" / 일별 추이 → >= DATEADD(day, -N, GETDATE()) AND < DATEADD(day, 1, CAST(GETDATE() AS date)) (또는 <= GETDATE())
5. 특정 연도/월이 명시된 경우 → 리터럴 날짜 사용
6. 날짜 범위는 BETWEEN보다 >= AND < 형식 권장"""


def get_date_mode() -> str:
    if MES_DATE_MODE in ("production", "prod", "operational"):
        return "production"
    return "dev_last_year"


def date_rules_for_prompt() -> str:
    if get_date_mode() == "production":
        return _PRODUCTION_RULES
    return _DEV_LAST_YEAR_RULES


def date_policy_summary() -> str:
    if get_date_mode() == "production":
        return "운영 DB: 날짜 기준 = GETDATE() (실무 일반)"
    return "개발 DB: 날짜 기준 = 1년 전 (운영 동일 실데이터 구간, 최근 dev 데이터 제외)"
