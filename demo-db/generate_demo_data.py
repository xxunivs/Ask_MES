"""
공개용 데모 DB에 가상 데이터 채우기

column_spec.json (칸별 값 종류와 범위)과 데모 DB의 표 정의를 읽어,
표끼리 ID가 맞물리는 가상 데이터를 만든다. 실제 기록은 쓰지 않는다.
같은 SEED 로 돌리면 항상 같은 데이터가 나온다.

실행: backend/ 에서
  ./venv/bin/python ../demo-db/generate_demo_data.py
"""
from __future__ import annotations

import json
import random
import re
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.demo_db import connect  # noqa: E402

SEED = 42
SPEC = json.loads((Path(__file__).parent / "column_spec.json").read_text(encoding="utf-8"))
SCHEMA = {t["name"]: t for t in json.loads((ROOT / "backend/data/mes_schema.json").read_text(encoding="utf-8"))["tables"]}
SITE_ID = "1000"
# 가상 데이터 날짜 범위
DATE_START = datetime(2025, 11, 1)
DATE_END = datetime(2026, 10, 20)
BATCH = 500

# 표별 행 수 (부모 표가 먼저 오도록 정렬)
ROW_COUNTS = {
    "CIM_CODECLASS": 20, "CIM_CODE": 200,
    "CIM_FACILITY": 20, "CIM_FACILITYMAP": 20,
    "CIM_EQUIPMENTCLASS": 30, "CIM_EQUIPMENT": 200,
    "CIM_PRODUCTCLASS": 10, "CIM_PRODUCTDEFINITION": 100,
    "CIM_PROCESSDEFINITION": 10, "CIM_PROCESSSEGMENT": 30, "CIM_PROCESSNODE": 60, "CIM_PROCESSPATH": 60,
    "CIM_PRODUCTPROCESSREL": 100, "CIM_PROCESSSEGMENTEQUIPMENTREL": 100,
    "CIM_MATERIALCLASS": 10, "CIM_MATERIALDEFINITION": 100, "CIM_MATERIALLOT": 1000,
    "CIM_DEFECTCLASS": 10, "CIM_DEFECT": 50,
    "CIM_PRODUCTORDER": 1000, "CIM_LOT": 5000, "CIM_LOTHIST": 15000,
    "CIM_BATCH": 200, "CIM_LOTBATCHREL": 1000, "CIM_LOTDEFECT": 1500, "CIM_LOTMATERIALLOTREL": 3000,
}

# 스키마 파일에 없는 참조 관계
EXTRA_REFS = {
    ("CIM_PROCESSPATH", "NEXTPROCESSNODEID"): "CIM_PROCESSNODE",
    ("CIM_PROCESSNODE", "SUBPROCESSDEFINITIONID"): "CIM_PROCESSDEFINITION",
}

rng = random.Random(SEED)
generated_ids: dict[str, list[str]] = {}


def load_columns(cur) -> dict[str, list[dict]]:
    """데모 DB 표 정의 (칸 이름, 종류, 길이, NULL 허용, PK 여부)"""
    cur.execute("""
        SELECT c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE, c.CHARACTER_MAXIMUM_LENGTH,
               c.NUMERIC_PRECISION, c.NUMERIC_SCALE, c.IS_NULLABLE,
               CASE WHEN k.COLUMN_NAME IS NULL THEN 0 ELSE 1 END
        FROM INFORMATION_SCHEMA.COLUMNS c
        LEFT JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE k
          ON k.TABLE_NAME = c.TABLE_NAME AND k.COLUMN_NAME = c.COLUMN_NAME AND k.CONSTRAINT_NAME LIKE 'PK[_]%'
        ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION""")
    tables: dict[str, list[dict]] = {}
    for t, name, dtype, length, prec, scale, nullable, is_pk in cur.fetchall():
        tables.setdefault(t, []).append({
            "name": name, "type": dtype, "length": length, "precision": prec, "scale": scale,
            "nullable": nullable == "YES", "pk": bool(is_pk),
        })
    return tables


def owner_table(table: str, column: str) -> str | None:
    """이 칸이 가리키는 부모 표 (FK 정의, 추가 관계, 이름 규칙 순)"""
    if (table, column) in EXTRA_REFS:
        return EXTRA_REFS[(table, column)]
    for fk in SCHEMA.get(table, {}).get("foreign_keys", []):
        if fk["column"] == column and "via" not in fk.get("label", "") and fk["ref_table"] in ROW_COUNTS:
            return fk["ref_table"]
    if column.endswith("ID"):
        candidate = "CIM_" + column[:-2]
        if candidate in ROW_COUNTS and candidate != table:
            return candidate
    return None


def own_id_column(table: str, columns: list[dict]) -> str | None:
    """표 자신의 ID 칸 (PK 중 SITEID 가 아니고 부모를 가리키지 않는 첫 칸)"""
    for c in columns:
        if c["pk"] and c["name"] != "SITEID" and not owner_table(table, c["name"]):
            return c["name"]
    return None


def fill_shape(shape: str, number: int) -> str:
    """모양 문자열의 9 자리는 번호로, A 는 고정 영문, 가 는 한글로 채움"""
    digits = str(number)
    out = []
    slots = shape.count("9")
    padded = digits.zfill(slots)[-slots:] if slots else ""
    i = 0
    for ch in shape:
        if ch == "9":
            out.append(padded[i]); i += 1
        elif ch == "A":
            out.append("D")
        elif ch == "가":
            out.append("가")
        else:
            out.append(ch)
    return "".join(out)


# 표별 ID 시작 번호 (0이 길게 이어지지 않도록 큰 수에서 시작)
id_starts: dict[str, int] = {}


def make_id(table: str, column: str, n: int, spec: dict) -> str:
    shapes = [s for s in spec.get("shapes", []) if "9" in s]
    if not shapes:
        return f"{column[:3]}{n:06d}"
    slots = shapes[0].count("9")
    if table not in id_starts:
        id_starts[table] = rng.randint(10 ** (slots - 1), 5 * 10 ** (slots - 1))
    return fill_shape(shapes[0], id_starts[table] + n * 7)


def random_date(base: datetime, column: str) -> datetime:
    """행 기준 시각 주변 날짜. 시작 계열은 앞, 종료 계열은 뒤"""
    upper = column.upper()
    if any(k in upper for k in ("START", "TRACKIN", "CREATE", "RELEASE", "PLAN")):
        return base + timedelta(minutes=rng.randint(0, 120))
    if any(k in upper for k in ("END", "TRACKOUT", "LASTEVENT", "COMPLETE", "FINISH", "UPDATE")):
        return base + timedelta(hours=rng.randint(2, 48))
    if "DELIVERY" in upper or "DUE" in upper:
        return base + timedelta(days=rng.randint(3, 30))
    return base + timedelta(minutes=rng.randint(0, 2880))


def fit(value, col: dict):
    """칸 종류와 길이에 맞게 값 변환"""
    if value is None:
        return None
    t = col["type"]
    if t in ("varchar", "nvarchar", "char", "nchar"):
        s = str(value)
        return s[: col["length"]] if col["length"] and col["length"] > 0 else s
    if t in ("int", "bigint"):
        return int(float(value))
    if t in ("numeric", "decimal"):
        return Decimal(str(round(float(value), col["scale"] or 0)))
    if t == "float":
        return float(value)
    return value


def generic_value(table: str, col: dict, spec: dict, n: int, base: datetime):
    name = col["name"]
    kind = spec.get("kind", "empty")
    if col["type"] in ("datetime2", "datetime") or kind == "date":
        return random_date(base, name)
    if kind == "code":
        values, weights = zip(*spec["values"].items())
        return rng.choices(values, weights)[0]
    if kind == "number":
        low, high = spec["low"], max(spec["high"], spec["low"])
        v = rng.uniform(low, high)
        return round(v) if spec.get("integer") else round(v, 2)
    if kind == "text":
        if re.search(r"USER", name):
            return f"user{rng.randint(1, 30):02d}"
        if re.search(r"NAME", name):
            return f"{SCHEMA.get(table, {}).get('label', table)}-{n:04d}"
        if re.search(r"DESC|COMMENT|NOTE|REMARK|TEXT", name):
            return f"가상 데이터 {n}"
        shapes = spec.get("shapes") or ["A999"]
        return fill_shape(rng.choice(shapes), rng.randint(1, 10 ** 6))
    return None


def build_rows(table: str, columns: list[dict]) -> list[dict]:
    count = ROW_COUNTS[table]
    spec = SPEC.get(table, {})
    own = own_id_column(table, columns)
    pk_cols = [c["name"] for c in columns if c["pk"]]
    seen_pk: set[tuple] = set()
    rows = []
    n = 0
    while len(rows) < count and n < count * 5:
        n += 1
        base = DATE_START + timedelta(seconds=rng.randint(0, int((DATE_END - DATE_START).total_seconds())))
        row = {}
        for col in columns:
            name = col["name"]
            cspec = spec.get(name, {})
            parent = owner_table(table, name)
            if name == "SITEID":
                value = SITE_ID
            elif name == own:
                numeric = col["type"] not in ("varchar", "nvarchar", "char", "nchar")
                value = n if numeric else make_id(table, name, n, cspec)
            elif parent and generated_ids.get(parent):
                value = rng.choice(generated_ids[parent])
            elif not col["pk"] and col["nullable"] and rng.random() < cspec.get("empty_ratio", 1.0):
                value = None
            else:
                value = generic_value(table, col, cspec, n, base)
                if value is None and (col["pk"] or not col["nullable"]):
                    value = f"{name[:3]}{n:06d}" if col["type"] in ("varchar", "nvarchar", "char", "nchar") else 0
            row[name] = fit(value, col)
        apply_domain_rules(table, row)
        key = tuple(row.get(c) for c in pk_cols)
        if key in seen_pk:
            continue
        seen_pk.add(key)
        rows.append(row)
    if own:
        generated_ids[table] = [r[own] for r in rows]
    return rows


def apply_domain_rules(table: str, row: dict) -> None:
    """업무상 말이 되도록 맞추는 값"""
    if table == "CIM_LOT" and row.get("QTY") is not None:
        qty = float(row["QTY"])
        loss = round(qty * rng.uniform(0, 0.05))
        if "LOSSQTY" in row:
            row["LOSSQTY"] = type(row["QTY"])(loss) if not isinstance(row["QTY"], Decimal) else Decimal(loss)
        if "ORIGINALQTY" in row:
            row["ORIGINALQTY"] = type(row["QTY"])(qty + loss) if not isinstance(row["QTY"], Decimal) else Decimal(qty + loss)
    if table == "CIM_LOT" and "ISHOLD" in row:
        row["ISHOLD"] = "Y" if rng.random() < 0.05 else "N"
    if table == "CIM_LOTDEFECT" and "DEFECTQTY" in row:
        row["DEFECTQTY"] = float(rng.randint(1, 20))


def insert(cur, conn, table: str, columns: list[dict], rows: list[dict]) -> None:
    names = [c["name"] for c in columns]
    sql = f"INSERT INTO [{table}] ({', '.join('[' + n + ']' for n in names)}) VALUES ({', '.join(['%s'] * len(names))})"
    for i in range(0, len(rows), BATCH):
        cur.executemany(sql, [tuple(r[n] for n in names) for r in rows[i:i + BATCH]])
        conn.commit()


def main() -> None:
    with connect() as conn:
        cur = conn.cursor()
        tables = load_columns(cur)
        for table in ROW_COUNTS:
            cur.execute(f"DELETE FROM [{table}]")
        conn.commit()
        for table in ROW_COUNTS:
            rows = build_rows(table, tables[table])
            insert(cur, conn, table, tables[table], rows)
            print(f"{table}: {len(rows)}행", flush=True)


if __name__ == "__main__":
    main()
