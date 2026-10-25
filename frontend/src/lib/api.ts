const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

export type QueryData = {
  columns: string[];
  rows: Record<string, unknown>[];
  count: number;
};

export type TraceStep = {
  step: string;
  detail: string;
};

export type NlToSqlResponse = {
  success: boolean;
  sql: string;
  data: QueryData | null;
  db_error: string | null;
  trace: TraceStep[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, init);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail ?? `서버 오류 (${resp.status})`);
  }
  return resp.json() as Promise<T>;
}

export function askQuestion(question: string, limit = 500) {
  return request<NlToSqlResponse>("/chat/nl-to-sql", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, limit }),
  });
}

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

export function listTables() {
  return request<TableGroup[]>("/data/tables");
}

export function readTable(name: string, page: number) {
  return request<TablePage>(`/data/tables/${encodeURIComponent(name)}?page=${page}`);
}
