"""
/chat 라우터
  POST /chat/nl-to-sql   : 자연어 → SQL 생성 + DB 실행
  POST /chat/analyze     : 조회된 데이터에 대한 분석 질문
  GET  /chat/health      : Ollama 연결 상태 확인
"""
import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Any

from core.ollama import llm_generate, check_ollama
from core.retriever import retrieve_context
from core.db_client import execute_sql

router = APIRouter()

# ─────────────────────────────────────────────
# 요청/응답 모델
# ─────────────────────────────────────────────

class NlToSqlRequest(BaseModel):
    question: str
    limit: int = 100


class AnalyzeRequest(BaseModel):
    question: str
    data: Optional[dict] = None  # { columns: [...], rows: [{...}] }


# ─────────────────────────────────────────────
# 프롬프트 템플릿
# ─────────────────────────────────────────────

NL_TO_SQL_PROMPT = """당신은 MES(제조실행시스템) 전문 SQL 생성 어시스턴트입니다.
아래 MES 스키마 정보를 참고하여 사용자의 자연어 질문을 MS SQL Server SELECT 쿼리로 변환하세요.

## MES 스키마 정보
{schema}

## 규칙
1. SELECT 문만 생성 (INSERT/UPDATE/DELETE/DROP/EXEC 절대 금지)
2. MS SQL Server 문법 사용. WITH (NOLOCK) 힌트를 모든 테이블에 적용하세요.
3. 컬럼/테이블명은 반드시 스키마에 있는 이름 그대로 사용 (존재하지 않는 컬럼 사용 금지)

## 날짜 규칙
4. [중요] 기본 기준일은 항상 1년 전이다. 사용자가 날짜를 별도로 지정하지 않으면 DATEADD(year, -1, GETDATE())를 기준으로 사용하라.
   - "오늘" / 날짜 미지정 → DATEADD(year, -1, GETDATE())
   - "어제" → DATEADD(day, -1, DATEADD(year, -1, CAST(GETDATE() AS date)))
   - "이번 달" → 1년 전 같은 달: YEAR(DATEADD(year,-1,GETDATE())), MONTH(DATEADD(year,-1,GETDATE()))
   - "이번 주" → DATEADD(year,-1,GETDATE()) 기준 해당 주
   - "최근 N일" → DATEADD(day, -N, DATEADD(year, -1, GETDATE())) ~ DATEADD(year, -1, GETDATE())
5. 특정 연도/월이 명시된 경우 (예: "2025년 12월") → 리터럴 날짜 사용 (GETDATE() 계산 금지)
   예시: TRACKINTIME >= '2025-12-01' AND TRACKINTIME < '2026-01-01'
6. 날짜 범위 필터는 BETWEEN보다 >= AND < 형식 사용

## 집계/추이 규칙
9. 일별 추이 집계 시 날짜 컬럼은 CONVERT(date, 날짜컬럼) 사용
10. 설비 가동 횟수 추이 → CIM_LOT 테이블의 TRACKINTIME + EQUIPMENTID로 COUNT(*) 집계
    (CIM_EQUIPMENT.RUNCOUNT는 현재 누적값이므로 추이 분석에 사용 금지)
11. 불량률 계산 → SUM(LOSSQTY) / NULLIF(SUM(ORIGINALQTY), 0) * 100

## alias 규칙
12. 컬럼 alias에 SQL 예약어 사용 금지: DATE, TIME, NAME, VALUE, COUNT, STATE, TYPE, DATA, KEY, INDEX, ORDER
    예시: AS DATE (X) → AS 작업일자 (O), AS COUNT (X) → AS 건수 (O)

## 응답 형식
반드시 아래 JSON 형식으로만 응답 (마크다운 코드블록 없이):
{{"sql": "SELECT ...", "description": "한국어로 쿼리 설명"}}

## 사용자 질문
{question}

JSON 응답:"""


ANALYZE_PROMPT = """당신은 MES 데이터 분석 전문가입니다.
다음 데이터를 분석하여 한국어로 명확하고 간결하게 답변하세요.

## 데이터 컬럼
{columns}

## 데이터 샘플 (최대 20행)
{rows}

## 사용자 질문
{question}

분석 결과를 3-5문장으로 요약하세요. 수치 근거를 포함하세요."""


# ─────────────────────────────────────────────
# 유틸리티
# ─────────────────────────────────────────────

def _parse_llm_json(raw: str) -> tuple[str, str]:
    """LLM 응답에서 sql, description 추출. 실패 시 raw 그대로 반환"""
    # 마크다운 코드블록 제거
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    # JSON 블록 추출 시도
    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if json_match:
        try:
            obj = json.loads(json_match.group())
            return obj.get("sql", ""), obj.get("description", "")
        except json.JSONDecodeError:
            pass

    # Fallback: SELECT 구문 직접 추출
    sql_match = re.search(r'(SELECT\s.+?)(?:;|$)', raw, re.DOTALL | re.IGNORECASE)
    sql = sql_match.group(1).strip() if sql_match else raw
    return sql, ""


def _rows_to_text(columns: list, rows: list, max_rows: int = 20) -> str:
    """rows(dict 배열) → 텍스트 표 변환"""
    if not rows:
        return "(데이터 없음)"
    lines = ["\t".join(str(c) for c in columns)]
    for row in rows[:max_rows]:
        if isinstance(row, dict):
            lines.append("\t".join(str(row.get(c, "")) for c in columns))
        elif isinstance(row, (list, tuple)):
            lines.append("\t".join(str(v) for v in row))
    return "\n".join(lines)


# ─────────────────────────────────────────────
# 엔드포인트
# ─────────────────────────────────────────────

@router.post("/nl-to-sql")
async def nl_to_sql(req: NlToSqlRequest):
    """
    자연어 → RAG 컨텍스트 → Ollama SQL 생성 → mes-api 실행
    반환: { success, sql, description, data }
    """
    # 1. RAG: 관련 스키마 청크 조회
    try:
        schema_ctx = retrieve_context(req.question)
    except Exception as e:
        schema_ctx = "(스키마 정보 조회 실패)"
        print(f"[RAG] 오류: {e}")

    # 2. LLM: SQL 생성
    prompt = NL_TO_SQL_PROMPT.format(schema=schema_ctx, question=req.question)
    try:
        raw_response = await llm_generate(prompt, temperature=0.05, max_tokens=512)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Ollama 연결 오류: {e}")

    sql, description = _parse_llm_json(raw_response)
    if not sql:
        raise HTTPException(status_code=500, detail="SQL 생성 실패 — LLM 응답을 파싱할 수 없습니다.")

    if not description:
        description = f'"{req.question}" 조회 결과'

    # 3. DB 실행 (mes-api 위임)
    db_data = None
    db_error = None
    try:
        db_result = await execute_sql(sql, limit=req.limit)
        # rows를 dict 배열 형식으로 정규화
        db_data = {
            "columns": db_result.get("columns", []),
            "rows": db_result.get("rows", []),   # [{col: val, ...}]
            "count": db_result.get("count", 0),
        }
    except Exception as e:
        db_error = str(e)
        print(f"[DB] 오류: {e}")

    return {
        "success": True,
        "sql": sql,
        "description": description,
        "data": db_data,
        "db_error": db_error,
    }


@router.post("/analyze")
async def analyze(req: AnalyzeRequest):
    """
    조회된 데이터 + 사용자 질문 → Ollama 분석 텍스트 반환
    """
    if not req.data:
        return {"success": True, "answer": "분석할 데이터가 없습니다. 먼저 데이터를 조회해 주세요."}

    columns = req.data.get("columns", [])
    rows = req.data.get("rows", [])
    rows_text = _rows_to_text(columns, rows)

    prompt = ANALYZE_PROMPT.format(
        columns=", ".join(str(c) for c in columns),
        rows=rows_text,
        question=req.question,
    )
    try:
        answer = await llm_generate(prompt, temperature=0.3, max_tokens=400)
        return {"success": True, "answer": answer}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Ollama 연결 오류: {e}")


@router.get("/health")
async def chat_health():
    """Ollama 연결 상태 확인"""
    ollama_ok = await check_ollama()
    return {
        "ollama": "ok" if ollama_ok else "연결 실패",
        "model": "qwen2.5:7b",
    }
