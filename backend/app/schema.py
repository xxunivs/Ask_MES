from __future__ import annotations

import json
from functools import lru_cache

from app.config import DATA_DIR

SCHEMA_PATH = DATA_DIR / "mes_schema.json"


@lru_cache(maxsize=1)
def schema_tables() -> list[dict]:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)["tables"]


@lru_cache(maxsize=1)
def tables_by_name() -> dict[str, dict]:
    return {t["name"]: t for t in schema_tables()}


@lru_cache(maxsize=1)
def column_names() -> dict[str, frozenset[str]]:
    return {t["name"].upper(): frozenset(c["name"].upper() for c in t.get("columns", [])) for t in schema_tables()}


def has_table(table: str) -> bool:
    return table.upper() in column_names()


def has_column(table: str, column: str) -> bool:
    return column.upper() in column_names().get(table.upper(), frozenset())
