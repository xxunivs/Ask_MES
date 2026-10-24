from __future__ import annotations

import json
import re
from typing import Any

from app.validation.code_values import code_values_prompt_hint
from app.validation.concept_alignment import alignment_prompt_rules
from app.generation.date_policy import date_rules_for_prompt
from app.validation.sql_validator import ValidationResult, allowed_tables_hint, get_schema_registry


NL_TO_SQL_PROMPT = """MES 질문을 간결한 MS SQL Server SELECT로 변환하세요.

## 스키마
{schema}

## 실제 DB
{db_context}

## 규칙
1. SELECT 문만 생성 (INSERT/UPDATE/DELETE/DROP/EXEC 절대 금지)
2. MS SQL Server 문법 사용. WITH (NOLOCK) 힌트를 모든 테이블에 적용하세요.
3. 컬럼/테이블명은 반드시 스키마에 있는 이름 그대로 사용 (존재하지 않는 컬럼 사용 금지)

## 날짜 규칙
{date_rules}

## 집계/추이 규칙
9. 일별 추이 집계 시 날짜 컬럼은 CONVERT(date, 날짜컬럼) 사용
   월별 추이는 CONVERT(char(7), 날짜컬럼, 120) 으로 월 단위로 묶고, 기간 미명시면 최근 12개월
   "A별 추이"처럼 항목이 함께 나오면 날짜와 A 컬럼을 SELECT, GROUP BY 에 모두 넣기
10. 설비 가동 횟수 추이 → CIM_LOT 테이블의 TRACKINTIME + EQUIPMENTID로 COUNT(*) 집계
    (CIM_EQUIPMENT.RUNCOUNT는 현재 누적값이므로 추이 분석에 사용 금지)
11. 불량률 계산 → SUM(LOSSQTY) / NULLIF(SUM(ORIGINALQTY), 0) * 100

## alias 규칙
12. 컬럼 alias에 SQL 예약어 사용 금지: DATE, TIME, NAME, VALUE, COUNT, STATE, TYPE, DATA, KEY, INDEX, ORDER
    예시: AS DATE (X) → AS 작업일자 (O), AS COUNT (X) → AS 건수 (O)

## 스키마 화이트리스트 (필수)
13. 아래에 없는 CIM_* 테이블·컬럼 이름을 만들지 마세요.
{schema_whitelist}

## 코드값 (허용 값, WHERE 절 리터럴)
14. Y/N 플래그는 TRUE/FALSE/1/0 대신 아래 허용 값만 사용.
{code_values}

## 질의-테이블 매핑
15. 아래 질의 유형은 지정 테이블을 반드시 사용.
{alignment_rules}

## 단순 조회 (중요)
16. 단일 테이블로 답할 수 있는 목록·집계·필터 질의는 **JOIN 하지 마세요**.
17. SELECT * 금지. 스키마에 있는 컬럼만 명시.
18. 환각 컬럼 금지: NODENAME→PROCESSNODENAME, SEGMENTNAME→PROCESSSEGMENTNAME, ORDERID→PRODUCTORDERID, SAFETYSTOCKYN→SAFETY_QTY, 자재이름 LOTNAME→MATERIALLOTNAME
19. **SELECT DISTINCT 금지.** 일부 테이블에서 DB 오류 발생. 대신 SELECT TOP 1000 또는 GROUP BY 사용.
    예시: SELECT DISTINCT FACILITYID (X) → SELECT TOP 1000 FACILITYID (O)
20. **컬럼 alias에 작은따옴표(\' \') 사용 금지.** 예: AS \'이름\' (X) → AS 이름 (O)
21. **테이블 alias는 반드시 WITH (NOLOCK) 앞에 위치.** 예: FROM CIM_LOT WITH(NOLOCK) L (X) → FROM CIM_LOT L WITH(NOLOCK) (O)
22. **테이블을 괄호로 감싸지 마세요.** 예: FROM (CIM_LOT WITH(NOLOCK)) (X) → FROM CIM_LOT WITH(NOLOCK) (O)
23. **목록·조회 질의에는 반드시 행 수를 제한하세요.** WHERE 조건이 없으면 `SELECT TOP 1000` 을 붙입니다.
    제한 없는 전체 조회는 차단됩니다. 예: SELECT LOTID FROM CIM_LOT WITH(NOLOCK) (X)
    → SELECT TOP 1000 LOTID FROM CIM_LOT WITH(NOLOCK) (O)
    (COUNT/SUM 등 집계만 하는 질의는 제한이 필요 없습니다)
24. **컬럼 alias 에 공백을 쓰지 마세요.** 예: AS LOT 건수 (X) → AS LOT건수 (O)

첫 글자부터 한 줄 JSON만 응답하고 사고과정·설명·마크다운은 출력하지 마세요:
{{"sql":"SELECT ..."}}

## 질문
{question}

JSON 응답:"""


def static_prompt_hints() -> dict:
    return {
        "date_rules": date_rules_for_prompt(),
        "schema_whitelist": allowed_tables_hint(),
        "code_values": code_values_prompt_hint() or "(코드값 사전 없음)",
        "alignment_rules": alignment_prompt_rules(),
    }


def build_schema_correction_prompt(
    question: str,
    schema_ctx: str,
    invalid_sql: str,
    validation: ValidationResult,
    db_context: str = "",
    error: str = "",
) -> str:
    err = error or validation.error_message()
    valid_sample = ", ".join(sorted(get_schema_registry().table_names)[:12])
    cv = code_values_prompt_hint() or "(없음)"
    return f"""이전에 생성한 SQL에 스키마 오류가 있습니다. mes_schema.json에 정의된 이름만 사용해 다시 작성하세요.

## 오류 내용
{err}

## 잘못된 SQL
{invalid_sql}

## MES 스키마 정보
{schema_ctx}

## 실제 DB
{db_context or "(없음)"}

## 날짜 규칙
{date_rules_for_prompt()}

## 허용 테이블 (일부)
{valid_sample} ... (총 {len(get_schema_registry().table_names)}개 CIM_* 테이블)

## 필수 규칙
- CIM_MATERIAL 테이블은 존재하지 않음. 자재 LOT → CIM_MATERIALLOT, 자재 정의·안전재고 → CIM_MATERIALDEFINITION
- 컬럼/테이블명은 스키마에 있는 이름만 사용
- SELECT만, 모든 테이블에 WITH (NOLOCK)
- SELECT * 금지. NODENAME/SEGMENTNAME/ORDERID/SAFETYSTOCKYN/MATERIALID 컬럼 금지
- 단일 테이블 목록 질의는 JOIN 하지 말 것. CIM_BATCH.LOTID 컬럼 없음 (LOT 연결은 CIM_LOTBATCHREL)
- 자재 LOT 이름 → MATERIALLOTNAME (LOTNAME은 CIM_LOT 전용)

## 코드값 (WHERE 절 리터럴)
{cv}

## 질의-테이블 매핑
{alignment_prompt_rules()}

## 사용자 질문
{question}

반드시 JSON만 응답: {{"sql": "SELECT ...", "description": "..."}}
JSON 응답:"""


def build_db_correction_prompt(
    question: str,
    schema_ctx: str,
    failed_sql: str,
    db_error: str,
    db_context: str = "",
) -> str:
    cv = code_values_prompt_hint() or "(없음)"
    return f"""이전 SQL은 스키마 검증은 통과했으나 MES DB 실행에 실패했습니다. 오류를 참고해 단순하고 실행 가능한 SELECT로 다시 작성하세요.

## DB 오류
{db_error[:500]}

## 실패한 SQL
{failed_sql}

## MES 스키마 정보
{schema_ctx}

## 실제 DB
{db_context or "(없음)"}

## 날짜 규칙
{date_rules_for_prompt()}

## 수정 지침
- 불필요한 JOIN 제거. 단일 테이블로 가능하면 JOIN 하지 마세요.
- SELECT * 금지. WITH (NOLOCK) 모든 테이블에 적용.
- JOIN은 스키마 FK 관계만 사용 (CIM_BATCH.LOTID 같은 컬럼 없음).
- 복잡한 서브쿼리·DATEDIFF 계산 대신 스키마에 있는 컬럼을 직접 SELECT.

## 코드값
{cv}

## 질의-테이블 매핑
{alignment_prompt_rules()}

## 사용자 질문
{question}

반드시 JSON만 응답: {{"sql": "SELECT ...", "description": "..."}}
JSON 응답:"""


def parse_llm_json(raw: str) -> dict[str, Any]:
    raw = re.sub(r"```[a-zA-Z]*", "", raw).strip().rstrip("`").strip()

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", raw):
        try:
            obj, _ = decoder.raw_decode(raw[match.start():])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue

    # SELECT 구문 직접 추출, 실패 시 빈 문자열 (raw 반환 시 코드펜스 찌꺼기가 SQL 로 실행됨)
    sql_match = re.search(r'(SELECT\s.+?)(?:;|$)', raw, re.DOTALL | re.IGNORECASE)
    sql = sql_match.group(1).strip() if sql_match else ""
    return {"sql": sql, "description": ""}
