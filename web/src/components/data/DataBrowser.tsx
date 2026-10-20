"use client";

import { useEffect, useState } from "react";
import { listTables, readTable, type TableGroup, type TablePage } from "@/lib/api";

// 데이터 둘러보기: 왼쪽 표 목록, 오른쪽 표 내용 50줄씩
export default function DataBrowser() {
  const [groups, setGroups] = useState<TableGroup[]>([]);
  const [selected, setSelected] = useState("CIM_LOT");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<TablePage | null>(null);
  const [error, setError] = useState("");
  // 받아 둔 데이터가 지금 고른 표, 페이지와 다르면 불러오는 중
  const loading = !error && (data?.name !== selected || data?.page !== page);

  useEffect(() => {
    listTables().then(setGroups).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    let cancelled = false;
    readTable(selected, page)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [selected, page]);

  function choose(name: string) {
    setError("");
    setSelected(name);
    setPage(1);
  }

  function movePage(delta: number) {
    setError("");
    setPage((p) => p + delta);
  }

  return (
    <div className="grid h-full grid-cols-[240px_1fr] overflow-hidden">
      <aside className="space-y-5 overflow-y-auto border-r border-hairline bg-canvas p-4">
        {groups.map((g) => (
          <div key={g.group}>
            <p className="mb-1 text-xs font-semibold text-ink-mute">{g.group}</p>
            <ul>
              {g.tables.map((t) => (
                <li key={t.name}>
                  <button
                    onClick={() => choose(t.name)}
                    className={`w-full rounded-md px-3 py-1.5 text-left text-sm ${
                      t.name === selected ? "bg-primary text-white" : "hover:bg-canvas-soft"
                    }`}
                  >
                    {t.label}
                    <span className={`block text-[11px] ${t.name === selected ? "text-white/60" : "text-ink-faint"}`}>
                      {t.name}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </aside>

      <section className="flex min-w-0 flex-col overflow-hidden p-6">
        <div className="mb-4 flex items-end justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-[22px] leading-[1.1] font-normal tracking-[-0.315px]">{data?.label ?? selected}</h2>
            <p className="mt-1 truncate text-sm text-ink-mute">
              {data?.description} {data && `· 칸 ${data.columns.length}개`}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2 text-sm">
            <button
              onClick={() => movePage(-1)}
              disabled={page === 1 || loading}
              className="rounded-md border border-hairline-dark px-3 py-1.5 disabled:opacity-30"
            >
              이전
            </button>
            <span className="w-16 text-center">{page} 페이지</span>
            <button
              onClick={() => movePage(1)}
              disabled={loading || (data?.rows.length ?? 0) < (data?.page_size ?? 50)}
              className="rounded-md border border-hairline-dark px-3 py-1.5 disabled:opacity-30"
            >
              다음
            </button>
          </div>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <div className={`min-h-0 flex-1 overflow-auto rounded-md border border-hairline bg-canvas ${loading ? "opacity-50" : ""}`}>
          {data && (
            <table className="text-left text-xs">
              <thead className="sticky top-0 bg-canvas-soft">
                <tr>
                  {data.columns.map((c) => (
                    <th key={c.name} className="px-3 py-2 align-bottom whitespace-nowrap">
                      <span className="block font-semibold">{c.label || c.name}</span>
                      {c.label && <span className="block text-[10px] font-normal text-ink-faint">{c.name}</span>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, i) => (
                  <tr key={i} className="border-t border-hairline">
                    {data.columns.map((c) => (
                      <td key={c.name} className="px-3 py-1.5 whitespace-nowrap">
                        {String(row[c.name] ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>
    </div>
  );
}
