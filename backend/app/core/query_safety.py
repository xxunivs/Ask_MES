"""
sqlparse 구문 트리 기반 Query Safety Layer (DDL/DML, 전체 스캔, 시스템 테이블, 다중 문장 차단)
정규식은 주석 삽입(`SEL/**/ECT`), 이스케이프, 서브쿼리로 우회되므로 토큰 트리로 판단
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import sqlparse
from sqlparse import tokens as T
from sqlparse.sql import Comment, Token, TokenList

# 출현 즉시 차단 키워드
_FORBIDDEN_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT",
    "DROP", "CREATE", "ALTER", "TRUNCATE", "RENAME",
    "GRANT", "REVOKE", "DENY",
    "EXEC", "EXECUTE", "CALL",
    "BACKUP", "RESTORE", "SHUTDOWN", "KILL",
    "BULK", "OPENROWSET", "OPENDATASOURCE", "OPENQUERY", "OPENXML",
    "INTO",  # SELECT ... INTO 의 테이블 생성 방지
}

# 메타데이터 및 시스템 객체 접두어
_SYSTEM_PREFIXES = (
    "SYS.", "SYSTEM.", "INFORMATION_SCHEMA.",
    "MASTER.", "MSDB.", "TEMPDB.", "MODEL.",
    "SYSOBJECTS", "SYSCOLUMNS", "SYSDATABASES", "SYSUSERS",
)

_RISK_LABELS = {
    "ddl_dml": "DDL/DML 등 읽기 전용이 아닌 연산",
    "full_scan": "WHERE·TOP 없는 전체 스캔",
    "system_table": "시스템 테이블·메타데이터 접근",
    "multi_statement": "세미콜론으로 이어붙인 다중 문장",
    "not_select": "SELECT 로 시작하지 않는 문장",
    "unparsable": "파싱 불가",
}


@dataclass
class SafetyVerdict:
    ok: bool
    risks: list[str] = field(default_factory=list)
    detail: str = ""

    def error_message(self) -> str:
        if self.ok:
            return ""
        labels = [_RISK_LABELS.get(r, r) for r in self.risks]
        msg = "; ".join(labels)
        return f"{msg} — {self.detail}" if self.detail else msg


def _strip_comments(statement: TokenList) -> list[Token]:
    """주석과 공백 제거 평탄화 토큰 목록, `SEL/**/ECT` 류 난독화 무력화"""
    out: list[Token] = []
    for tok in statement.flatten():
        if tok.ttype in T.Comment or isinstance(tok, Comment):
            continue
        if tok.is_whitespace:
            continue
        out.append(tok)
    return out


def _upper_values(toks: list[Token]) -> list[str]:
    return [t.value.upper() for t in toks]


def _has_forbidden_keyword(toks: list[Token]) -> Optional[str]:
    for tok in toks:
        if tok.ttype in T.Keyword or tok.ttype in T.Keyword.DDL or tok.ttype in T.Keyword.DML:
            word = tok.value.upper()
            if word in _FORBIDDEN_KEYWORDS:
                return word
    return None


def _touches_system_object(toks: list[Token]) -> Optional[str]:
    for tok in toks:
        if tok.ttype in T.Name or tok.ttype is T.String.Symbol:
            name = tok.value.upper().strip("[]\"'")
            for prefix in _SYSTEM_PREFIXES:
                if name == prefix.rstrip(".") or name.startswith(prefix):
                    return tok.value
    # 점 표기(sys . objects)로 흩어진 경우 대비
    joined = "".join(v for v in _upper_values(toks) if v not in {" "})
    for prefix in _SYSTEM_PREFIXES:
        if prefix in joined:
            return prefix.rstrip(".")
    return None


def _is_full_scan(toks: list[Token]) -> bool:
    words = set(_upper_values(toks))
    if words & {"WHERE", "TOP", "LIMIT", "OFFSET", "FETCH"}:
        return False
    # 집계 전용 질의는 결과가 작아 전체 스캔 허용
    if words & {"COUNT", "SUM", "AVG", "MIN", "MAX", "GROUP"}:
        return False
    return True


def validate_query(sql: str, *, allow_full_scan: bool = False) -> SafetyVerdict:
    """SQL 한 건의 파스트리 검증, allow_full_scan 은 전체 스캔 차단 해제용"""
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        return SafetyVerdict(False, ["unparsable"], "빈 문자열")

    parsed = sqlparse.parse(text)
    if not parsed:
        return SafetyVerdict(False, ["unparsable"], "sqlparse 가 문장을 얻지 못함")

    # 내용 있는 문장이 둘 이상이면 다중 문장으로 차단
    real = [s for s in parsed if s.token_first(skip_cm=True) is not None]
    if len(real) > 1:
        return SafetyVerdict(
            False, ["multi_statement"], f"문장 {len(real)}개가 이어붙어 있음"
        )

    statement = real[0]
    toks = _strip_comments(statement)
    if not toks:
        return SafetyVerdict(False, ["unparsable"], "주석 제거 후 토큰 없음")

    risks: list[str] = []
    details: list[str] = []

    first = toks[0].value.upper()
    if first not in {"SELECT", "WITH"}:
        risks.append("not_select")
        details.append(f"첫 키워드 {first}")

    bad = _has_forbidden_keyword(toks)
    if bad:
        risks.append("ddl_dml")
        details.append(bad)

    sysobj = _touches_system_object(toks)
    if sysobj:
        risks.append("system_table")
        details.append(sysobj)

    if not allow_full_scan and _is_full_scan(toks):
        risks.append("full_scan")

    if risks:
        return SafetyVerdict(False, risks, ", ".join(details))
    return SafetyVerdict(True)
