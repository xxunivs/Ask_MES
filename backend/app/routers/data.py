"""
/data 라우터 (데이터 둘러보기)
  GET /data/tables               : 종류별 표 목록과 칸 설명
  GET /data/tables/{name}?page=1 : 표 내용 50줄씩
  GET /data/demo-progress        : 데모 DB 표별 행 수 (가상 데이터 생성 진행 확인)
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from fastapi import APIRouter, HTTPException

from app.core.demo_db import table_row_counts
from app.core.sql_executor import execute_sql

router = APIRouter()

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "../../data/mes_schema.json")
PAGE_SIZE = 50

# 사용자 화면용 데이터 종류 묶음
GROUPS: list[tuple[str, list[str]]] = [
    ("생산 LOT", ["CIM_LOT", "CIM_LOTHIST", "CIM_BATCH", "CIM_LOTBATCHREL", "CIM_LOTMATERIALLOTREL"]),
    ("설비", ["CIM_EQUIPMENT", "CIM_EQUIPMENTCLASS", "CIM_FACILITY", "CIM_FACILITYMAP", "CIM_PROCESSSEGMENTEQUIPMENTREL"]),
    ("불량", ["CIM_LOTDEFECT", "CIM_DEFECT", "CIM_DEFECTCLASS"]),
    ("작업지시, 제품", ["CIM_PRODUCTORDER", "CIM_PRODUCTDEFINITION", "CIM_PRODUCTCLASS", "CIM_PRODUCTPROCESSREL"]),
    ("자재", ["CIM_MATERIALLOT", "CIM_MATERIALDEFINITION", "CIM_MATERIALCLASS"]),
    ("공정", ["CIM_PROCESSDEFINITION", "CIM_PROCESSNODE", "CIM_PROCESSPATH", "CIM_PROCESSSEGMENT"]),
    ("기준 코드", ["CIM_CODE", "CIM_CODECLASS"]),
]


@lru_cache(maxsize=1)
def _schema() -> dict[str, dict]:
    with open(_SCHEMA_PATH, encoding="utf-8") as f:
        return {t["name"]: t for t in json.load(f)["tables"]}


def _table_summary(name: str) -> dict:
    t = _schema().get(name, {})
    return {
        "name": name,
        "label": t.get("label") or name,
        "description": t.get("description", ""),
    }


@router.get("/tables")
def list_tables():
    """종류별 표 목록"""
    return [
        {"group": group, "tables": [_table_summary(n) for n in names]}
        for group, names in GROUPS
    ]


@router.get("/tables/{name}")
async def read_table(name: str, page: int = 1):
    """표 내용 한 페이지. 표 이름은 스키마 목록에 있는 것만 허용"""
    if name not in _schema():
        raise HTTPException(status_code=404, detail=f"없는 표: {name}")
    page = max(page, 1)
    sql = (
        f"SELECT * FROM {name} WITH (NOLOCK) "
        f"ORDER BY (SELECT NULL) OFFSET {(page - 1) * PAGE_SIZE} ROWS FETCH NEXT {PAGE_SIZE} ROWS ONLY"
    )
    try:
        result = await execute_sql(sql, limit=PAGE_SIZE)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"DB 조회 실패: {e}")

    labels = {c["name"]: c.get("description") or "" for c in _schema()[name].get("columns", [])}
    return {
        **_table_summary(name),
        "page": page,
        "page_size": PAGE_SIZE,
        "columns": [{"name": c, "label": labels.get(c, "")} for c in result.get("columns", [])],
        "rows": result.get("rows", []),
    }


@router.get("/demo-progress")
def demo_progress():
    """데모 DB 표별 행 수"""
    try:
        counts = table_row_counts()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"데모 DB 접속 실패: {e}")
    return [
        {"group": group, "tables": [{**_table_summary(n), "rows": counts.get(n, 0)} for n in names]}
        for group, names in GROUPS
    ]
