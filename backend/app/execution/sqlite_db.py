from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta

import sqlglot
from sqlglot import exp
from sqlglot.dialects.sqlite import SQLite

from app.config import SQLITE_PATH

# T-SQL 날짜 함수는 SQLite 에 맞는 것이 없어 아래 파이썬 함수로 같은 의미를 구현
_EPOCH = datetime(1900, 1, 1)


def _to_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return _EPOCH + timedelta(days=value)
    try:
        return datetime.fromisoformat(str(value)[:19])
    except ValueError:
        return None


def _fmt(d: datetime | None) -> str | None:
    return d.strftime("%Y-%m-%d %H:%M:%S") if d else None


def _add_months(d: datetime, n: int) -> datetime:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    days = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return d.replace(year=y, month=m, day=min(d.day, days[m - 1]))


def _dateadd(unit: str, n, base) -> str | None:
    d = _to_dt(base)
    if d is None or n is None:
        return None
    n = int(n)
    unit = unit.upper()
    if unit in ("YEAR", "YY", "YYYY"):
        d = _add_months(d, 12 * n)
    elif unit in ("QUARTER", "QQ", "Q"):
        d = _add_months(d, 3 * n)
    elif unit in ("MONTH", "MM", "M"):
        d = _add_months(d, n)
    elif unit in ("WEEK", "WK", "WW"):
        d += timedelta(weeks=n)
    elif unit in ("HOUR", "HH"):
        d += timedelta(hours=n)
    elif unit in ("MINUTE", "MI", "N"):
        d += timedelta(minutes=n)
    elif unit in ("SECOND", "SS", "S"):
        d += timedelta(seconds=n)
    else:
        d += timedelta(days=n)
    return _fmt(d)


def _datediff(unit: str, start, end) -> int | None:
    a, b = _to_dt(start), _to_dt(end)
    if a is None or b is None:
        return None
    unit = unit.upper()
    # T-SQL DATEDIFF 는 경과 시간이 아니라 경계를 넘은 횟수
    if unit in ("YEAR", "YY", "YYYY"):
        return b.year - a.year
    if unit in ("QUARTER", "QQ", "Q"):
        return (b.year - a.year) * 4 + (b.month - 1) // 3 - (a.month - 1) // 3
    if unit in ("MONTH", "MM", "M"):
        return (b.year - a.year) * 12 + b.month - a.month
    if unit in ("WEEK", "WK", "WW"):
        return ((b.date() - a.date()).days + (a.isoweekday() % 7)) // 7
    if unit in ("HOUR", "HH"):
        return int((b.replace(minute=0, second=0) - a.replace(minute=0, second=0)).total_seconds() // 3600)
    if unit in ("MINUTE", "MI", "N"):
        return int((b.replace(second=0) - a.replace(second=0)).total_seconds() // 60)
    if unit in ("SECOND", "SS", "S"):
        return int((b - a).total_seconds())
    return (b.date() - a.date()).days


def _datepart(unit: str, value) -> int | None:
    d = _to_dt(value)
    if d is None:
        return None
    unit = unit.upper()
    parts = {
        "YEAR": d.year, "QUARTER": (d.month - 1) // 3 + 1, "MONTH": d.month, "DAY": d.day,
        "WEEK": int(d.strftime("%U")) + 1, "WEEKDAY": d.isoweekday() % 7 + 1, "DAYOFYEAR": d.timetuple().tm_yday,
        "HOUR": d.hour, "MINUTE": d.minute, "SECOND": d.second,
    }
    return parts.get(unit)


def _unit(e: exp.Expression) -> exp.Literal:
    return exp.Literal.string(e.text("unit") or "DAY")


class _TSQLToSQLite(SQLite):
    class Generator(SQLite.Generator):
        TRANSFORMS = {
            **SQLite.Generator.TRANSFORMS,
            exp.DateAdd: lambda self, e: self.func("TSQL_DATEADD", _unit(e), e.expression, e.this),
            exp.DateDiff: lambda self, e: self.func("TSQL_DATEDIFF", _unit(e), e.expression, e.this),
            exp.Extract: lambda self, e: self.func("TSQL_DATEPART", exp.Literal.string(e.this.name), e.expression),
            exp.TimeStrToTime: lambda self, e: self.sql(e.this),
            exp.CurrentTimestamp: lambda self, e: "TSQL_NOW()",
            exp.CurrentDate: lambda self, e: "DATE(TSQL_NOW())",
        }


def translate(sql: str) -> str:
    return sqlglot.transpile(sql, read="tsql", write=_TSQLToSQLite)[0]


QUERY_TIMEOUT_SEC = 15


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True, check_same_thread=False)
    conn.create_function("TSQL_NOW", 0, lambda: _fmt(datetime.now()))
    conn.create_function("TSQL_DATEADD", 3, _dateadd)
    conn.create_function("TSQL_DATEDIFF", 3, _datediff)
    conn.create_function("TSQL_DATEPART", 2, _datepart)
    conn.create_function("YEAR", 1, lambda v: _datepart("YEAR", v))
    conn.create_function("MONTH", 1, lambda v: _datepart("MONTH", v))
    conn.create_function("DAY", 1, lambda v: _datepart("DAY", v))
    conn.create_function("NUMBER_TO_STR", 2, lambda v, _: None if v is None else str(v))
    # SQLite 는 자체 실행 시간 제한이 없어 무거운 SQL 이 서버를 붙잡음
    deadline = time.monotonic() + QUERY_TIMEOUT_SEC
    conn.set_progress_handler(lambda: time.monotonic() > deadline, 100_000)
    return conn

