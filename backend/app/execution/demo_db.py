from __future__ import annotations

import pymssql

from app.config import (
    DEMO_DB_HOST,
    DEMO_DB_NAME,
    DEMO_DB_PASSWORD,
    DEMO_DB_PORT,
    DEMO_DB_READER_PASSWORD,
    DEMO_DB_READER_USER,
    DEMO_DB_USER,
)


def connect() -> pymssql.Connection:
    return pymssql.connect(
        server=DEMO_DB_HOST,
        port=DEMO_DB_PORT,
        user=DEMO_DB_USER,
        password=DEMO_DB_PASSWORD,
        database=DEMO_DB_NAME,
        login_timeout=5,
    )


def connect_reader() -> pymssql.Connection:
    return pymssql.connect(
        server=DEMO_DB_HOST,
        port=DEMO_DB_PORT,
        user=DEMO_DB_READER_USER,
        password=DEMO_DB_READER_PASSWORD,
        database=DEMO_DB_NAME,
        login_timeout=5,
    )
