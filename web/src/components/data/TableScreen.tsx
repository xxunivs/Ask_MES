"use client";

import { useEffect, useState } from "react";
import { readTable, type TablePage } from "@/lib/api";
import { ConditionField, ConditionPanel, GridFooter, ListTab } from "@/components/mes/MesParts";

export default function TableScreen({ table }: { table: string }) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<TablePage | null>(null);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<number | null>(null);
  // 별도 상태 대신 받아 둔 데이터와 현재 페이지 비교로 불러오는 중 판단
  const loading = !error && data?.page !== page;

  useEffect(() => {
    let cancelled = false;
    readTable(table, page)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [table, page]);

  function movePage(delta: number) {
    setError("");
    setPicked(null);
    setPage((p) => Math.max(1, p + delta));
  }

  const firstRow = (page - 1) * (data?.page_size ?? 50) + 1;

  return (
    <div className="flex h-full flex-col bg-panel">
      <ConditionPanel>
        <ConditionField label="테이블">
          <span className="inline-block w-56 border border-panel-line bg-white px-2 py-0.5">{table}</span>
        </ConditionField>
        <ConditionField label="페이지">
          <span className="inline-block w-16 border border-panel-line bg-white px-2 py-0.5 text-right">{page}</span>
        </ConditionField>
      </ConditionPanel>

      <div className="flex min-h-0 flex-1 flex-col px-1">
        <ListTab />
        {error && <p className="bg-white px-3 py-2 text-mark">{error}</p>}
        <div className={`min-h-0 flex-1 overflow-auto border border-panel-line bg-white ${loading ? "opacity-50" : ""}`}>
          {data && (
            <table className="border-collapse whitespace-nowrap">
              <thead className="sticky top-0 z-10 bg-grid-head text-white">
                <tr>
                  <th className="border border-frame-line px-2 py-1">
                    <input type="checkbox" disabled />
                  </th>
                  <th className="border border-frame-line px-2 py-1 font-normal">No</th>
                  {data.columns.map((c) => (
                    <th key={c.name} className="border border-frame-line px-2 py-1 font-normal" title={c.name}>
                      {c.label || c.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, i) => (
                  <tr
                    key={i}
                    onClick={() => setPicked(i)}
                    className={picked === i ? "bg-grid-pick" : i % 2 ? "bg-grid-alt" : "bg-white"}
                  >
                    <td className="border border-grid-line px-2 text-center">
                      <input type="checkbox" checked={picked === i} readOnly />
                    </td>
                    <td className="border border-grid-line px-2 text-right text-[#5c6168]">{firstRow + i}</td>
                    {data.columns.map((c) => {
                      const v = row[c.name];
                      return (
                        <td
                          key={c.name}
                          className={`border border-grid-line px-2 py-0.5 ${typeof v === "number" ? "text-right" : ""}`}
                        >
                          {formatCell(v)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <GridFooter
          page={page}
          from={data ? firstRow : 0}
          count={data?.rows.length ?? 0}
          canPrev={page > 1 && !loading}
          canNext={!loading && (data?.rows.length ?? 0) >= (data?.page_size ?? 50)}
          onFirst={() => movePage(1 - page)}
          onPrev={() => movePage(-1)}
          onNext={() => movePage(1)}
          note={`칸 ${data?.columns.length ?? 0}개`}
        />
      </div>
    </div>
  );
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return v.slice(0, 19).replace("T", " ");
  return String(v);
}
