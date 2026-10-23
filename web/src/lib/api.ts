// 백엔드(FastAPI) 호출 모음

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

// 조회 결과 표
export type QueryData = {
  columns: string[];
  rows: Record<string, unknown>[];
  count: number;
};

// 처리 과정 한 단계
export type TraceStep = {
  step: string;
  detail: string;
};

// POST /chat/nl-to-sql 응답
export type NlToSqlResponse = {
  success: boolean;
  sql: string;
  description: string;
  data: QueryData | null;
  db_error: string | null;
  trace: TraceStep[];
};

// 공통 POST 요청
async function post<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail ?? `서버 오류 (${resp.status})`);
  }
  return resp.json() as Promise<T>;
}

// 자연어 질문을 SQL로 바꿔 실행
export function askQuestion(question: string, limit = 100) {
  return post<NlToSqlResponse>("/chat/nl-to-sql", { question, limit });
}

// 데이터 둘러보기

export type TableSummary = {
  name: string;
  label: string;
  description: string;
};

export type TableGroup = {
  group: string;
  tables: TableSummary[];
};

export type TablePage = TableSummary & {
  page: number;
  page_size: number;
  columns: { name: string; label: string }[];
  rows: Record<string, unknown>[];
};

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail ?? `서버 오류 (${resp.status})`);
  }
  return resp.json() as Promise<T>;
}

// 종류별 표 목록
export function listTables() {
  return get<TableGroup[]>("/data/tables");
}

// 표 내용 한 페이지
export function readTable(name: string, page: number) {
  return get<TablePage>(`/data/tables/${encodeURIComponent(name)}?page=${page}`);
}
