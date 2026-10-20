/**
 * NL→SQL 변환 & 분석 API 클라이언트
 * 환경변수 VITE_LLM_API_URL 없으면 localhost:8001 사용
 */
const LLM_API_URL = import.meta.env.VITE_LLM_API_URL || "http://localhost:8001";

// ─────────────────────────────────────────────
// 자연어 → SQL 변환 + DB 실행
// 반환: { sql, description, data: { columns, rows, count } | null, db_error }
// ─────────────────────────────────────────────
export async function convertNlToSql(text, limit = 100) {
  const resp = await fetch(`${LLM_API_URL}/chat/nl-to-sql`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question: text, limit }),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `서버 오류 (${resp.status})`);
  }

  const result = await resp.json();
  return {
    sql: result.sql,
    description: result.description,
    data: result.data,         // { columns: [...], rows: [{...}], count: N } | null
    db_error: result.db_error, // DB 실행 실패 시 오류 메시지
    trace: result.trace,       // 단계별 중간 결과 [{ step, detail }]
  };
}

// ─────────────────────────────────────────────
// 조회된 데이터에 대한 분석 질문
// 반환: { type: "text", content: "..." }
// ─────────────────────────────────────────────
export async function getAnalysisResponse(text, data = null) {
  const resp = await fetch(`${LLM_API_URL}/chat/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question: text, data }),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `서버 오류 (${resp.status})`);
  }

  const result = await resp.json();
  return { type: "text", content: result.answer };
}
