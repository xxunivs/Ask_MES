"""
MSSQL에서 추출한 JSON을 mes_schema.json 형식으로 변환하는 스크립트

사용법:
  1. MSSQL에서 아래 쿼리 실행 후 결과를 raw_schema.json으로 저장
  2. python convert_schema.py

MSSQL 쿼리:
  SELECT
      t.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE,
      c.CHARACTER_MAXIMUM_LENGTH, c.IS_NULLABLE,
      CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 'YES' ELSE 'NO' END AS IS_PK
  FROM INFORMATION_SCHEMA.TABLES t
  JOIN INFORMATION_SCHEMA.COLUMNS c ON t.TABLE_NAME = c.TABLE_NAME
  LEFT JOIN (
      SELECT ku.TABLE_NAME, ku.COLUMN_NAME
      FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
      JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
      WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
  ) pk ON c.TABLE_NAME = pk.TABLE_NAME AND c.COLUMN_NAME = pk.COLUMN_NAME
  WHERE t.TABLE_TYPE = 'BASE TABLE' AND t.TABLE_NAME LIKE 'CIM_%'
  ORDER BY t.TABLE_NAME, c.ORDINAL_POSITION
  FOR JSON PATH
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

INPUT_FILE = "raw_schema.json"
OUTPUT_FILE = "data/mes_schema.json"

COLUMN_DESCRIPTIONS = {
    "SITEID": "사이트 ID",
    "ACTIVITY": "활동/이벤트명 (TrackIn, TrackOut, Defect 등)",
    "PREVACTIVITY": "이전 활동명",
    "CUSTOMACTIVITY": "커스텀 활동명",
    "PREVCUSTOMACTIVITY": "이전 커스텀 활동명",
    "LASTEVENTTIME": "마지막 이벤트 발생시간",
    "LASTEVENTSEQ": "이벤트 시퀀스 (PK, HIST 테이블)",
    "ISUSABLE": "사용가능여부 (Y/N)",
    "DESCRIPTION": "설명",
    "REASONCODE": "사유코드",
    "COMMENTS": "비고",
    "CREATOR": "생성자",
    "CREATETIME": "생성시간",
    "MODIFIER": "수정자",
    "MODIFYTIME": "수정시간",
    "TID": "트랜잭션 ID",
    "STATE": "상태",
    "PREVSTATE": "이전 상태",
    "LOCATION": "공정/위치",
    "PREVLOCATION": "이전 공정/위치",
    "EQUIPMENTID": "설비 ID (FK)",
    "LOTID": "LOT ID (FK)",
    "PROCESSSEGMENTID": "공정 세그먼트 ID (FK)",
    "PROCESSNODEID": "공정 노드 ID (FK)",
    "PROCESSDEFINITIONID": "공정 정의 ID (FK)",
    "PRODUCTORDERID": "작업지시 ID (FK)",
    "WORKORDERID": "작업계획오더 ID (FK)",
    "PRODUCTDEFINITIONID": "제품 정의 ID (FK)",
    "MATERIALDEFINITIONID": "자재 정의 ID (FK)",
    "MATERIALCLASSID": "자재 클래스 ID (FK)",
    "QTY": "수량",
    "ORIGINALQTY": "원래수량",
    "LOSSQTY": "불량/손실수량",
    "PRIORITY": "우선순위",
    "SEQUENCE": "순서/시퀀스",
    "STARTTIME": "실적 시작시간",
    "ENDTIME": "실적 종료시간",
    "SCHEDULESTARTTIME": "계획 시작시간",
    "SCHEDULEENDTIME": "계획 종료시간",
}

def format_type(col):
    dtype = col["DATA_TYPE"]
    length = col.get("CHARACTER_MAXIMUM_LENGTH")
    if length and length != -1:
        return f"{dtype}({length})"
    return dtype

def get_description(col_name, table_name):
    if col_name in COLUMN_DESCRIPTIONS:
        return COLUMN_DESCRIPTIONS[col_name]
    if col_name.endswith("ID") and col_name != "SITEID":
        return f"{col_name} (ID)"
    if col_name.endswith("NAME"):
        return f"{col_name[:-4]} 이름"
    if col_name.endswith("TIME"):
        return f"{col_name[:-4]} 시간"
    if col_name.endswith("QTY"):
        return f"{col_name[:-3]} 수량"
    if col_name.startswith("IS"):
        return f"{col_name[2:]} 여부 (Y/N)"
    return col_name

def get_table_description(table_name, pk_cols):
    pk_str = ", ".join(pk_cols) if pk_cols else ""
    suffix = ""
    if table_name.endswith("HIST"):
        suffix = " 이력 테이블"
    elif table_name.endswith("REL"):
        suffix = " 관계 테이블"
    pk_info = f" (PK: {pk_str})" if pk_str else ""
    return f"{table_name}{suffix}{pk_info}"

def convert(input_path, output_path):
    print(f"읽는 중: {input_path}")
    raw = Path(input_path).read_text(encoding="utf-8")
    rows = json.loads(raw)

    # 테이블별로 그룹핑
    tables_dict = defaultdict(list)
    for row in rows:
        tables_dict[row["TABLE_NAME"]].append(row)

    tables = []
    for table_name, cols in tables_dict.items():
        pk_cols = [c["COLUMN_NAME"] for c in cols if c.get("IS_PK") == "YES"]
        columns = []
        for col in cols:
            col_name = col["COLUMN_NAME"]
            columns.append({
                "name": col_name,
                "type": format_type(col),
                "description": get_description(col_name, table_name),
                "isPK": col.get("IS_PK") == "YES",
                "nullable": col.get("IS_NULLABLE") == "YES"
            })
        tables.append({
            "name": table_name,
            "description": get_table_description(table_name, pk_cols),
            "label": table_name,
            "pk": pk_cols,
            "columns": columns,
            "foreign_keys": []
        })

    schema = {
        "source": "MSSQL INFORMATION_SCHEMA (자동 추출)",
        "version": "auto",
        "domain": "MES 전체",
        "tables": tables
    }

    Path(output_path).write_text(
        json.dumps(schema, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"완료: {output_path}")
    print(f"  테이블 수: {len(tables)}")
    print(f"  컬럼 수: {sum(len(t['columns']) for t in tables)}")

if __name__ == "__main__":
    input_file = sys.argv[1] if len(sys.argv) > 1 else INPUT_FILE
    output_file = sys.argv[2] if len(sys.argv) > 2 else OUTPUT_FILE
    convert(input_file, output_file)
