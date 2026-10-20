"""
Query Safety Layer
- SELECT만 허용
- 위험 키워드 차단
- 결과 행 수 제한
"""

import re

# 허용 키워드 (SELECT 시작만 허용)
ALLOWED_START = ["select", "with"]

# 차단 키워드
BLOCKED_KEYWORDS = [
    "insert", "update", "delete", "drop", "truncate",
    "alter", "create", "exec", "execute", "xp_",
    "sp_", "shutdown", "grant", "revoke", "deny",
    "--", "/*", "*/", ";"
]

MAX_ROWS = 1000  # 최대 반환 행 수


def validate_query(sql: str) -> tuple[bool, str]:
    """
    SQL 유효성 검사
    Returns: (is_valid, error_message)
    """
    if not sql or not sql.strip():
        return False, "SQL이 비어 있습니다."

    sql_lower = sql.strip().lower()

    # SELECT 또는 WITH(CTE)로 시작해야 함
    starts_ok = any(sql_lower.startswith(kw) for kw in ALLOWED_START)
    if not starts_ok:
        return False, "SELECT 또는 WITH 구문만 허용됩니다."

    # 위험 키워드 검사
    for keyword in BLOCKED_KEYWORDS:
        if keyword in sql_lower:
            return False, f"허용되지 않는 키워드가 포함되어 있습니다: '{keyword}'"

    return True, ""
