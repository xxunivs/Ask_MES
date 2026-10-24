"""개발 DB 는 최근 데이터가 비운영이고 약 1년 전 구간만 운영과 같은 실데이터"""
from __future__ import annotations

import os

from app.config import DB_BACKEND

# 가상 데이터(SQLite)는 1년 전 구간 구분이 없어 운영 기준 사용
_DEFAULT_MODE = "production" if DB_BACKEND == "sqlite" else "dev_last_year"
MES_DATE_MODE = os.getenv("MES_DATE_MODE", _DEFAULT_MODE).strip().lower()

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
     (추이 질의에서 N이 없으면 N=30 적용)
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


