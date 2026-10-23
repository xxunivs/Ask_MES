"""
/data 라우터 (데이터 둘러보기)
  GET /data/tables               : 종류별 표 목록과 칸 설명
  GET /data/tables/{name}?page=1 : 표 내용 50줄씩
  GET /data/demo-progress        : 데모 DB 표별 행 수 (가상 데이터 생성 진행 확인)
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache

from fastapi import APIRouter, HTTPException

from app.core.demo_db import table_row_counts
from app.core.sql_executor import execute_sql

router = APIRouter()

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "../../data/mes_schema.json")
_EXTRA_LABELS_PATH = os.path.join(os.path.dirname(__file__), "../../data/display_labels_extra.json")
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


# 화면에 보이는 표 이름
TABLE_LABELS = {
    "CIM_LOT": "생산 로트", "CIM_LOTHIST": "로트 이력", "CIM_BATCH": "배치",
    "CIM_LOTBATCHREL": "로트-배치 관계", "CIM_LOTMATERIALLOTREL": "로트-자재로트 관계",
    "CIM_EQUIPMENT": "설비", "CIM_EQUIPMENTCLASS": "설비 분류", "CIM_FACILITY": "공정 구역",
    "CIM_FACILITYMAP": "공정 구역 계층", "CIM_PROCESSSEGMENTEQUIPMENTREL": "공정-설비 관계",
    "CIM_LOTDEFECT": "로트 불량", "CIM_DEFECT": "불량 코드", "CIM_DEFECTCLASS": "불량 분류",
    "CIM_PRODUCTORDER": "제품 작업지시", "CIM_PRODUCTDEFINITION": "제품 정의", "CIM_PRODUCTCLASS": "품목 구분",
    "CIM_PRODUCTPROCESSREL": "제품-공정 관계", "CIM_MATERIALLOT": "자재 로트", "CIM_MATERIALDEFINITION": "자재 정의",
    "CIM_MATERIALCLASS": "자재 클래스", "CIM_PROCESSDEFINITION": "공정 정의", "CIM_PROCESSNODE": "공정 노드",
    "CIM_PROCESSPATH": "공정 경로", "CIM_PROCESSSEGMENT": "공정 세그먼트", "CIM_CODE": "공통 코드",
    "CIM_CODECLASS": "코드 분류",
}


def _clean(label: str) -> str:
    return re.sub(r"\s*\(FK\)", "", label or "").strip()


@lru_cache(maxsize=1)
def _column_labels() -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """칸 화면 이름: 표별 설명, 같은 칸 이름의 다른 표 설명, 추가 이름표 순"""
    by_table: dict[str, dict[str, str]] = {}
    by_name: dict[str, str] = {}
    for name, t in _schema().items():
        for c in t.get("columns", []):
            label = _clean(c.get("description", ""))
            if label:
                by_table.setdefault(name, {})[c["name"]] = label
                by_name.setdefault(c["name"], label)
    with open(_EXTRA_LABELS_PATH, encoding="utf-8") as f:
        extra = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    for k, v in extra.items():
        by_name.setdefault(k, v)
    return by_table, by_name


@lru_cache(maxsize=1)
def _label_overrides() -> dict[str, str]:
    """스키마 설명이 영어인 칸의 한글 이름"""
    with open(_EXTRA_LABELS_PATH, encoding="utf-8") as f:
        return json.load(f).get("_override", {})


def _column_label(table: str, column: str) -> str:
    by_table, by_name = _column_labels()
    return _label_overrides().get(column) or by_table.get(table, {}).get(column) or by_name.get(column, "")


@lru_cache(maxsize=1)
def _schema() -> dict[str, dict]:
    with open(_SCHEMA_PATH, encoding="utf-8") as f:
        return {t["name"]: t for t in json.load(f)["tables"]}


def _table_summary(name: str) -> dict:
    t = _schema().get(name, {})
    return {
        "name": name,
        "label": TABLE_LABELS.get(name) or t.get("label") or name,
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

    return {
        **_table_summary(name),
        "page": page,
        "page_size": PAGE_SIZE,
        "columns": [{"name": c, "label": _column_label(name, c)} for c in result.get("columns", [])],
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
