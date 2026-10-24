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

export function askQuestion(question: string, limit = 100) {
  return post<NlToSqlResponse>("/chat/nl-to-sql", { question, limit });
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

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail ?? `서버 오류 (${resp.status})`);
  }
  return resp.json() as Promise<T>;
}

export function listTables() {
  return get<TableGroup[]>("/data/tables");
}

export function readTable(name: string, page: number) {
  return get<TablePage>(`/data/tables/${encodeURIComponent(name)}?page=${page}`);
}
