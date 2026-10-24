import pytest

from app.autofix.sql_autofix import autofix_sql
from app.validation.query_safety import validate_query


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM CIM_LOT",
        "SELECT TOP 1 LOTID FROM CIM_LOT; DROP TABLE CIM_LOT",
        "SELECT name FROM sys.tables",
        "SELECT LOTID FROM CIM_LOT",
        "SELECT TOP 1 LOTID INTO NEWTABLE FROM CIM_LOT",
    ],
)
def test_unsafe_queries_blocked(sql):
    assert not validate_query(sql).ok


def test_normal_query_allowed():
    assert validate_query("SELECT TOP 10 LOTID FROM CIM_LOT WITH (NOLOCK) WHERE ISHOLD = 'Y'").ok


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("SELECT L.LOTID FROM CIM_LOT WITH (NOLOCK) L", "FROM CIM_LOT L WITH (NOLOCK)"),
        ("SELECT LOTID AS 'LOT 번호' FROM CIM_LOT WITH (NOLOCK)", "AS [LOT 번호]"),
        ("SELECT DISTINCT STATE FROM CIM_LOT WITH (NOLOCK)", "SELECT TOP 1000 STATE"),
        ("SELECT TOP 5 CIM_LOT.LOTNAM FROM CIM_LOT WITH (NOLOCK)", "CIM_LOT.LOTNAME"),
        ("SELECT L.LOTID FROM CIM_LOT L WITH (NOLOCK)", "SELECT TOP 1000 L.LOTID"),
        (
            "SELECT TOP 5 CIM_DEFECT.DEFECTTYPENAME FROM CIM_LOTDEFECT LD WITH (NOLOCK) "
            "JOIN CIM_DEFECT D WITH (NOLOCK) ON LD.DEFECTID = D.DEFECTID",
            "SELECT TOP 5 D.DEFECTTYPENAME",
        ),
    ],
)
def test_autofix(sql, expected):
    fixed, _ = autofix_sql(sql)
    assert expected in fixed
