from app.execution import sqlite_db


def run(sql: str) -> list[tuple]:
    conn = sqlite_db.connect()
    try:
        return conn.execute(sqlite_db.translate(sql)).fetchall()
    finally:
        conn.close()


def test_getdate_is_last_data_day():
    assert run("SELECT GETDATE()")[0][0] == run("SELECT MAX(TRACKINTIME) FROM CIM_LOT")[0][0]


def test_convert_char_length_groups_by_month():
    rows = run(
        "SELECT TOP 3 CONVERT(char(7), TRACKINTIME, 120) AS m, COUNT(*) FROM CIM_LOT "
        "GROUP BY CONVERT(char(7), TRACKINTIME, 120) ORDER BY 1 DESC"
    )
    assert all(len(m) == 7 for m, _ in rows)


def test_top_and_nolock():
    assert len(run("SELECT TOP 5 LOTID FROM CIM_LOT WITH (NOLOCK)")) == 5


def test_dateadd():
    assert run("SELECT DATEADD(day, -30, '2026-10-20 00:00:00')")[0][0].startswith("2026-09-20")
