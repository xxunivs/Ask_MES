"""Query Safety Layer — 파스트리 기반 SQL 검증.

논문(NeuroFactory, Stage 4)의 Query Safety Layer 를 구현한 것이다. 생성된
SQL 을 문자열이 아니라 sqlparse 구문 트리로 보고 네 가지를 막는다.

  1. DDL/DML          — SELECT 외의 모든 문장
  2. 전체 스캔        — WHERE / TOP / LIMIT 이 전혀 없는 조회
  3. 시스템 테이블    — sys.*, INFORMATION_SCHEMA.*, master.. 등 메타데이터 접근
  4. 다중 문장        — 세미콜론으로 두 번째 문장을 붙이는 형태

정규식 필터를 쓰지 않는 이유는 주석 삽입(`SEL/**/ECT`), 문자열 이스케이프,
중첩 서브쿼리로 쉽게 우회되기 때문이다. 토큰 트리에서 판단하면 이런 난독화가
파싱 단계에서 그대로 드러난다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import sqlparse
from sqlparse import tokens as T
from sqlparse.sql import Comment, Token, TokenList

# SELECT 이외에 나타나면 즉시 차단하는 키워드
_FORBIDDEN_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT",
    "DROP", "CREATE", "ALTER", "TRUNCATE", "RENAME",
    "GRANT", "REVOKE", "DENY",
    "EXEC", "EXECUTE", "CALL",
    "BACKUP", "RESTORE", "SHUTDOWN", "KILL",
    "BULK", "OPENROWSET", "OPENDATASOURCE", "OPENQUERY", "OPENXML",
    "INTO",  # SELECT ... INTO 는 테이블을 만든다
}

# 메타데이터·시스템 객체 접근
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
    """검증 결과. `ok` 가 False 면 `risks` 에 위험 범주가 담긴다."""

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
    """주석을 제거한 평탄화 토큰 목록.

    `SEL/**/ECT` 같은 주석 난독화는 sqlparse 가 주석을 별도 토큰으로 떼어내므로
    여기서 걸러지고 남은 키워드가 그대로 보인다.
    """
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
    # 점 표기(sys . objects)로 흩어진 경우까지 잡는다
    joined = "".join(v for v in _upper_values(toks) if v not in {" "})
    for prefix in _SYSTEM_PREFIXES:
        if prefix in joined:
            return prefix.rstrip(".")
    return None


def _is_full_scan(toks: list[Token]) -> bool:
    """WHERE 도 TOP 도 LIMIT 도 없는 조회인지."""
    words = set(_upper_values(toks))
    if words & {"WHERE", "TOP", "LIMIT", "OFFSET", "FETCH"}:
        return False
    # 집계만 하는 질의는 전체 스캔이어도 결과가 작으므로 허용한다
    if words & {"COUNT", "SUM", "AVG", "MIN", "MAX", "GROUP"}:
        return False
    return True


def validate_query(sql: str, *, allow_full_scan: bool = False) -> SafetyVerdict:
    """SQL 한 건을 파스트리로 검증한다.

    allow_full_scan: 전체 스캔 차단만 끄고 싶을 때 (벤치마크 등).
    """
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        return SafetyVerdict(False, ["unparsable"], "빈 문자열")

    parsed = sqlparse.parse(text)
    if not parsed:
        return SafetyVerdict(False, ["unparsable"], "sqlparse 가 문장을 얻지 못함")

    # 세미콜론으로 붙인 두 번째 문장 — 내용이 있는 문장이 둘 이상이면 차단
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
