"""
실행 방법: python eval/check_validator.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.sql_validator import validate_sql  # noqa: E402

samples = [
    ("Q005", "작업지시", "SELECT CIM_PRODUCTORDER.ORDERID FROM CIM_PRODUCTORDER WITH (NOLOCK)"),
    ("Q007", "자재 LOT", "SELECT CIM_MATERIALLOT.LOTNAME FROM CIM_MATERIALLOT WHERE QTY=0"),
    ("Q008", "안전재고", "SELECT x FROM CIM_MATERIALDEFINITION WITH (NOLOCK) WHERE SAFETYSTOCKYN='Y'"),
    ("Q010", "불량유형", "SELECT DISTINCT CIM_DEFECTCLASS.DESCRIPTION FROM CIM_DEFECTCLASS"),
    ("Q015", "배치", "SELECT CIM_BATCH.BATCHID FROM CIM_BATCH WITH (NOLOCK) JOIN CIM_LOT ON CIM_BATCH.LOTID=CIM_LOT.LOTID"),
    ("Q018", "공정노드", "SELECT CIM_PROCESSNODE.NODENAME FROM CIM_PROCESSNODE WITH (NOLOCK)"),
    ("Q017", "제품정의", "SELECT DISTINCT CIM_PRODUCTDEFINITION.* FROM CIM_PRODUCTDEFINITION WITH (NOLOCK)"),
    ("Q050", "홀드", "SELECT TOP 10 LOTID FROM CIM_LOT WITH (NOLOCK) ORDER BYSUM(LOSSQTY) DESC"),
]

for qid, q, sql in samples:
    vr = validate_sql(sql, question=q)
    status = "BLOCK" if not vr.ok else "PASS"
    print(f"{qid} {status}: {vr.error_message()[:100]}")
