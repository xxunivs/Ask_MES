"""날짜 기준일 규칙 (실제 개발 DB: 1년 전, 가상 데이터: 오늘)"""

from __future__ import annotations

import os

from app.config import DB_BACKEND

# 실제 개발 DB: 최근 데이터는 시험용, 약 1년 전 구간만 운영과 같은 실데이터
_DEFAULT_MODE = "production" if DB_BACKEND == "sqlite" else "dev_last_year"
MES_DATE_MODE = (os.getenv("MES_DATE_MODE") or _DEFAULT_MODE).strip().lower()

_DEV_LAST_YEAR_RULES = [
    "날짜가 없으면 기준일은 1년 전 DATEADD(year, -1, GETDATE()). "
    "오늘: 기준일, 어제: DATEADD(day, -1, DATEADD(year, -1, CAST(GETDATE() AS date))), "
    "이번 달, 이번 주: 1년 전 같은 기간",
    "최근 N일, 일별 추이: TRACKINTIME >= DATEADD(day, -N, DATEADD(year, -1, GETDATE())) "
    "AND TRACKINTIME < DATEADD(year, -1, GETDATE()). 추이에서 N이 없으면 30",
]

_PRODUCTION_RULES = [
    "날짜가 없으면 기준일은 GETDATE(). 어제: DATEADD(day, -1, CAST(GETDATE() AS date))",
    "최근 N일, 일별 추이: >= DATEADD(day, -N, GETDATE()) AND < DATEADD(day, 1, CAST(GETDATE() AS date)). "
    "추이에서 N이 없으면 30",
]

_COMMON_RULES = [
    "연도나 월을 직접 말하면 그 날짜를 그대로 사용",
    "날짜 범위는 BETWEEN 대신 >= AND <",
]


def get_date_mode() -> str:
    return "production" if MES_DATE_MODE in ("production", "prod", "operational") else "dev_last_year"


def date_rules() -> list[str]:
    rules = _PRODUCTION_RULES if get_date_mode() == "production" else _DEV_LAST_YEAR_RULES
    return rules + _COMMON_RULES
