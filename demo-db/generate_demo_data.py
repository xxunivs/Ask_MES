"""
column_spec.json, vocab.py, 데모 DB 표 정의 기반의 공개용 데모 DB 가상 데이터 생성
표 간 ID 가 맞물리는 데이터, 실제 기록 미사용, 같은 SEED 면 같은 결과

실행 방법 (backend/ 에서):
  ./venv/bin/python ../demo-db/generate_demo_data.py
"""
from __future__ import annotations

import json
import random
import re
import sys
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).parent))

from app.core.demo_db import connect  # noqa: E402
import vocab  # noqa: E402

SEED = 42
SPEC = json.loads((Path(__file__).parent / "column_spec.json").read_text(encoding="utf-8"))
SCHEMA = {t["name"]: t for t in json.loads((ROOT / "backend/data/mes_schema.json").read_text(encoding="utf-8"))["tables"]}
SITE_ID = "1000"
DATE_START = datetime(2024, 10, 1)
DATE_END = datetime(2026, 10, 20)
BATCH = 500

# 표별 행 수, 부모 표가 먼저 오는 순서 유지 필요
ROW_COUNTS = {
    "CIM_CODECLASS": 20, "CIM_CODE": 200,
    "CIM_FACILITY": 20, "CIM_FACILITYMAP": 20,
    "CIM_EQUIPMENTCLASS": 12, "CIM_EQUIPMENT": 200,
    "CIM_PRODUCTCLASS": 10, "CIM_PRODUCTDEFINITION": 100,
    "CIM_PROCESSDEFINITION": 10, "CIM_PROCESSSEGMENT": 14, "CIM_PROCESSNODE": 60, "CIM_PROCESSPATH": 60,
    "CIM_PRODUCTPROCESSREL": 100, "CIM_PROCESSSEGMENTEQUIPMENTREL": 100,
    "CIM_MATERIALCLASS": 10, "CIM_MATERIALDEFINITION": 100, "CIM_MATERIALLOT": 1000,
    "CIM_DEFECTCLASS": 10, "CIM_DEFECT": 20,
    "CIM_PRODUCTORDER": 1000, "CIM_LOT": 5000, "CIM_LOTHIST": 15000,
    "CIM_BATCH": 200, "CIM_LOTBATCHREL": 1000, "CIM_LOTDEFECT": 1500, "CIM_LOTMATERIALLOTREL": 3000,
}
LOT_TABLES = {"CIM_LOT", "CIM_LOTHIST", "CIM_LOTDEFECT", "CIM_LOTBATCHREL", "CIM_LOTMATERIALLOTREL", "CIM_MATERIALLOT", "CIM_BATCH"}

# 실제 표본에선 비었지만 데모 질문에 필요한 칸 (채우는 비율, 값 종류)
DEMO_FILL = {
    ("CIM_MATERIALDEFINITION", "SAFETY_QTY"): (0.6, "number"),
    ("CIM_EQUIPMENT", "ALARMID"): (0.15, "alarm"),
    ("CIM_LOT", "DUEDATE"): (0.8, "date"),
    ("CIM_MATERIALLOT", "RECEIVEDTIME"): (0.9, "date"),
}
YN_FLAG = re.compile(r"^IS|FLAG$|YN$")
# 다른 표 ID 참조 칸의 접두어 (PREVPROCESSNODEID -> PROCESSNODEID)
REF_PREFIXES = ("PREV", "NEXT", "ROOTPARENT", "PARENT", "SOURCE", "RESERVED", "START", "ORIGINAL", "MERGE", "CHILD", "REPLACE", "SUB")

# 스키마 파일에 없는 참조 관계
EXTRA_REFS = {
    ("CIM_PROCESSPATH", "NEXTPROCESSNODEID"): "CIM_PROCESSNODE",
    ("CIM_PROCESSNODE", "SUBPROCESSDEFINITIONID"): "CIM_PROCESSDEFINITION",
}

rng = random.Random(SEED)
generated_ids: dict[str, list[str]] = {}
# 표별 ID 와 대표 이름 (자식 표 이름 생성용)
names: dict[str, dict[str, str]] = {}
# 표별 ID 와 행 (자식 표의 부모 값 참조용)
rows_by_id: dict[str, dict[str, dict]] = {}


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
    if not column.endswith("ID"):
        return None
    base = column
    for prefix in REF_PREFIXES:
        if base.startswith(prefix) and "CIM_" + base[len(prefix):-2] in ROW_COUNTS:
            base = base[len(prefix):]
            break
    candidate = "CIM_" + base[:-2]
    if candidate in ROW_COUNTS and (candidate != table or base != column):
        return candidate
    return None


def own_id_column(table: str, columns: list[dict]) -> str | None:
    """표 자신의 ID 칸 (PK 중 SITEID 가 아니고 부모를 가리키지 않는 첫 칸)"""
    for c in columns:
        if c["pk"] and c["name"] != "SITEID" and not owner_table(table, c["name"]):
            return c["name"]
    return None


def make_id(table: str, column: str, n: int) -> str:
    fmt = vocab.ID_FORMATS.get(table)
    if table == "CIM_PRODUCTCLASS":
        return vocab.PRODUCT_CLASSES[(n - 1) % len(vocab.PRODUCT_CLASSES)][0]
    if not fmt:
        return f"{column[:3]}{n:06d}"
    return fmt.format(n=vocab.ID_OFFSETS.get(table, 0) + n, n2=(n * 37) % 10000)


def random_code(length: int) -> str:
    return "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789") for _ in range(length))


def random_date(base: datetime, column: str) -> datetime:
    """행 기준 시각 주변 날짜, 시작 계열은 가깝게, 종료 계열은 뒤로"""
    upper = column.upper()
    if any(k in upper for k in ("START", "TRACKIN", "CREATE", "RELEASE", "PLAN")):
        return base + timedelta(minutes=rng.randint(0, 120))
    if any(k in upper for k in ("END", "TRACKOUT", "LASTEVENT", "COMPLETE", "FINISH", "UPDATE", "MODIFY")):
        return base + timedelta(hours=rng.randint(2, 48))
    if "DELIVERY" in upper or "DUE" in upper or "EXPIRE" in upper:
        return base + timedelta(days=rng.randint(3, 60))
    return base + timedelta(minutes=rng.randint(0, 2880))


def is_text(col: dict) -> bool:
    return col["type"] in ("varchar", "nvarchar", "char", "nchar")


def fit(value, col: dict):
    """칸 종류와 길이에 맞춘 값 변환"""
    if value is None:
        return None
    t = col["type"]
    if is_text(col):
        s = str(value)
        # varchar 는 한글 한 글자당 2바이트 (Korean_Wansung)
        limit = col["length"] if col["length"] and col["length"] > 0 else None
        if limit and t in ("varchar", "char"):
            while len(s.encode("cp949", errors="replace")) > limit:
                s = s[:-1]
            return s
        return s[:limit] if limit else s
    if t in ("int", "bigint"):
        return int(float(value))
    if t in ("numeric", "decimal"):
        return Decimal(str(round(float(value), col["scale"] or 0)))
    if t == "float":
        return float(value)
    return value


def is_yn_flag(col: dict, spec: dict) -> bool:
    """Y/N 표시 칸 (코드값이 Y, N 뿐이거나 IS, FLAG, YN 이름)"""
    if spec.get("kind") == "code":
        return set(spec["values"]) <= {"Y", "N"}
    return is_text(col) and bool(YN_FLAG.search(col["name"]))


def common_text(table: str, name: str, n: int):
    """여러 표 공통 칸의 값, 해당 없으면 None"""
    if name in ("ACTIVITY", "PREVACTIVITY"):
        return rng.choice(vocab.LOT_ACTIVITIES if table in LOT_TABLES else vocab.MASTER_ACTIVITIES)
    if name in ("CUSTOMACTIVITY", "PREVCUSTOMACTIVITY"):
        return None
    if name in ("CREATOR", "MODIFIER", "WORKER", "STARTWORKER", "TRANSFERUSER") or "USER" in name:
        return rng.choice(vocab.USERS)
    if name == "TID":
        return uuid.UUID(int=rng.getrandbits(128)).hex
    if re.match(r"^(DESCRIPTION|COMMENTS\d?|REMARK.*|S_REMARK|SPCOMMENTS)$", name):
        return rng.choice(vocab.COMMENTS) if rng.random() < 0.15 else None
    if name == "CUSTOMERNAME":
        return rng.choice(vocab.CUSTOMERS)
    return None


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
        return random_code(min(8, col["length"] or 8))
    return None


def demo_fill_value(table: str, col: dict, base: datetime):
    ratio, kind = DEMO_FILL[(table, col["name"])]
    if rng.random() >= ratio:
        return None
    if kind == "number":
        return rng.randint(10, 500)
    if kind == "alarm":
        return f"ALM{rng.randint(1, 40):03d}"
    return random_date(base, col["name"])


def name_of(table: str, key) -> str:
    return names.get(table, {}).get(key, "")


def apply_domain_rules(table: str, row: dict, n: int) -> str | None:
    """업무상 자연스러운 이름과 값 보정, 행의 대표 이름 반환"""
    def pick(items):
        return items[(n - 1) % len(items)]

    def size():
        return rng.choice([3, 4, 5, 6, 8, 10, 12, 16, 20])

    label = None
    def parent_row(parent: str, key: str) -> dict:
        return rows_by_id.get(parent, {}).get(row.get(key), {})

    if table in ("CIM_LOT", "CIM_PRODUCTORDER"):
        product = parent_row("CIM_PRODUCTDEFINITION", "PRODUCTDEFINITIONID")
        if product:
            row["PRODUCTCLASSID"] = product.get("PRODUCTCLASSID")
            if "PRODUCTTYPE" in row:
                row["PRODUCTTYPE"] = product.get("PRODUCTCLASSID")
    if table == "CIM_LOT":
        row["ROOTPARENTLOTID"] = row.get("LOTID")
        qty = rng.randint(20, 400)
        loss = round(qty * rng.uniform(0, 0.05))
        row.update(QTY=qty, LOSSQTY=loss, ORIGINALQTY=qty + loss)
        row["ISHOLD"] = "Y" if rng.random() < 0.05 else "N"
        row["LOTNAME"] = row.get("LOTID")
    elif table == "CIM_LOTHIST":
        row["LOTNAME"] = row.get("LOTID")
    elif table == "CIM_LOTDEFECT":
        row["DEFECTQTY"] = float(rng.randint(1, 20))
    elif table == "CIM_PROCESSSEGMENT":
        label = pick(vocab.PROCESS_SEGMENTS)
        row["PROCESSSEGMENTNAME"] = label
    elif table == "CIM_PROCESSDEFINITION":
        label = pick(vocab.PROCESS_DEFINITIONS)
        row["PROCESSDEFINITIONNAME"] = label
    elif table == "CIM_PROCESSNODE":
        label = f"{name_of('CIM_PROCESSDEFINITION', row.get('PROCESSDEFINITIONID'))} / {name_of('CIM_PROCESSSEGMENT', row.get('PROCESSSEGMENTID'))}"
        row["PROCESSNODENAME"] = label
    elif table == "CIM_EQUIPMENTCLASS":
        label = pick(vocab.EQUIPMENT_CLASSES)
        row["EQUIPMENTCLASSNAME"] = label
    elif table == "CIM_EQUIPMENT":
        label = f"{name_of('CIM_EQUIPMENTCLASS', row.get('EQUIPMENTCLASSID')) or '설비'} #{n:03d}"
        row["EQUIPMENTNAME"] = label
    elif table == "CIM_FACILITY":
        label = pick(vocab.FACILITIES)
        row["FACILITYNAME"] = label
    elif table == "CIM_PRODUCTCLASS":
        label = pick(vocab.PRODUCT_CLASSES)[1]
        row["PRODUCTCLASSNAME"] = label
    elif table == "CIM_PRODUCTDEFINITION":
        row["PRODUCTCLASSID"] = rng.choices(["FERT", "HALB"], [7, 3])[0]
        d = size()
        label = rng.choice(vocab.PRODUCT_SHAPES).format(f=rng.choice([2, 3, 4]), d=f"{d}.0", r=d / 2, m=rng.choice([6, 8, 10, 12]))
        row["PRODUCTDEFINITIONNAME"] = label
    elif table == "CIM_MATERIALCLASS":
        label = pick(vocab.MATERIAL_CLASSES)
        row["MATERIALCLASSNAME"] = label
    elif table == "CIM_MATERIALDEFINITION":
        label = rng.choice(vocab.MATERIAL_SHAPES).format(d=size())
        row["MATERIALDEFINITIONNAME"] = label
    elif table == "CIM_MATERIALLOT":
        row["MATERIALLOTNAME"] = row.get("MATERIALLOTID")
    elif table == "CIM_DEFECTCLASS":
        label = pick(vocab.DEFECT_CLASSES)
        row["DEFECTCLASSNAME"] = label
    elif table == "CIM_DEFECT":
        label = pick(vocab.DEFECTS)
        cls = next((c for k, c in vocab.DEFECT_CLASS_RULES if k in label), "가공 불량")
        row["DEFECTCLASSID"] = next(i for i, nm in names["CIM_DEFECTCLASS"].items() if nm == cls)
        row["DEFECTNAME"] = label
        row["DEFECTCLASSNAME"] = name_of("CIM_DEFECTCLASS", row.get("DEFECTCLASSID"))
        row["DEFECTTYPENAME"] = label
    elif table == "CIM_CODECLASS":
        label = pick(vocab.CODE_CLASSES)
        row["CODECLASSNAME"] = label
    elif table == "CIM_CODE":
        label = f"{name_of('CIM_CODECLASS', row.get('CODECLASSID'))} {n:03d}"
        row["CODENAME"] = label
        row["CODENAME_KO"] = label
    elif table == "CIM_BATCH":
        row["BATCHNAME"] = row.get("BATCHID")
    return label


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
                value = make_id(table, name, n) if is_text(col) else n
            elif parent == table:
                # 같은 표 참조 칸(부모 LOT 등)은 비움, 필요한 값만 규칙에서 보충
                value = None
            elif parent and generated_ids.get(parent):
                value = rng.choice(generated_ids[parent])
                if not col["pk"] and col["nullable"] and name != parent[4:] + "ID" and rng.random() < 0.5:
                    value = None
            elif (table, name) in DEMO_FILL:
                value = demo_fill_value(table, col, base)
            elif is_yn_flag(col, cspec):
                value = "Y" if rng.random() < 0.1 else "N"
            elif is_text(col) and (common := common_text(table, name, n)) is not None:
                value = common
            elif is_text(col) and name in ("CUSTOMACTIVITY", "PREVCUSTOMACTIVITY"):
                value = None
            elif not col["pk"] and col["nullable"] and rng.random() < cspec.get("empty_ratio", 1.0):
                value = None
            else:
                value = generic_value(table, col, cspec, n, base)
                if value is None and (col["pk"] or not col["nullable"]):
                    value = make_id(table, name, n) if is_text(col) else 0
            row[name] = value
        label = apply_domain_rules(table, row, n)
        row = {c["name"]: fit(row[c["name"]], c) for c in columns}
        key = tuple(row.get(c) for c in pk_cols)
        if key in seen_pk:
            continue
        seen_pk.add(key)
        rows.append(row)
        if own and label:
            names.setdefault(table, {})[row[own]] = label
    if own:
        generated_ids[table] = [r[own] for r in rows]
        rows_by_id[table] = {r[own]: r for r in rows}
    return rows


def insert(cur, conn, table: str, columns: list[dict], rows: list[dict]) -> None:
    cols = [c["name"] for c in columns]
    sql = f"INSERT INTO [{table}] ({', '.join('[' + n + ']' for n in cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
    for i in range(0, len(rows), BATCH):
        cur.executemany(sql, [tuple(r[n] for n in cols) for r in rows[i:i + BATCH]])
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
