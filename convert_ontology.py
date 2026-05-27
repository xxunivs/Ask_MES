"""
convert_ontology.py
====================
mes_ontology_fk.json (온톨로지 FK 형식)
  → mes_schema.json  (ChromaDB 시딩용 형식)

사용법:
  python convert_ontology.py [입력파일] [출력파일]

기본값:
  입력: mes_ontology_fk.json
  출력: data/mes_schema.json
"""

import json
import sys
import os


def convert(input_path: str, output_path: str):
    with open(input_path, encoding="utf-8") as f:
        onto = json.load(f)

    tables = []
    for c in onto["classes"]:
        table_name = c["table"]
        label      = c["label"]
        pk_cols    = c.get("pk", [])

        # ── 컬럼 변환 ──────────────────────────────────
        columns = []
        for col in c.get("columns", []):
            columns.append({
                "name":        col["column"],
                "type":        col["dataType"],
                "description": col.get("description", ""),
                "isPK":        col.get("isPK", False),
                "nullable":    col.get("nullable", True),
            })

        # ── FK 변환 (직접 FK + via-REL 경유) ───────────
        foreign_keys = []
        for op in c.get("objectProperties", []):
            if "fromCol" in op:
                # 직접 외래키
                foreign_keys.append({
                    "column":     op["fromCol"],
                    "ref_table":  op["range"],
                    "ref_column": op["toCol"],
                    "label":      op.get("label", ""),
                })
            elif "join" in op:
                # 중간 관계 테이블 경유 (N:M REL)
                joins = op["join"]
                if joins:
                    foreign_keys.append({
                        "column":     joins[0]["fromCol"],
                        "ref_table":  joins[0]["toTable"],
                        "ref_column": joins[0]["toCol"],
                        "label":      op.get("label", "") + " [via " + op.get("relTable", "") + "]",
                    })

        # 테이블 설명 = 한글 레이블 + PK 정보
        pk_str = ", ".join(pk_cols) if pk_cols else ""
        description = f"{label} (PK: {pk_str})" if pk_str else label

        tables.append({
            "name":         table_name,
            "description":  description,
            "label":        label,
            "pk":           pk_cols,
            "columns":      columns,
            "foreign_keys": foreign_keys,
        })

    result = {
        "source":  onto.get("source_erd", ""),
        "version": onto.get("version", ""),
        "domain":  onto.get("domain", ""),
        "tables":  tables,
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total_cols = sum(len(t["columns"]) for t in tables)
    total_fks  = sum(len(t["foreign_keys"]) for t in tables)
    print(f"[변환 완료] {input_path} → {output_path}")
    print(f"  테이블: {len(tables)}개 / 컬럼: {total_cols}개 / FK: {total_fks}개")
    for t in tables:
        print(f"  {t['name']:45s} | {t['label']:22s} | col={len(t['columns']):3d} | fk={len(t['foreign_keys'])}")


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "mes_ontology_fk.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "data/mes_schema.json"
    convert(inp, out)
