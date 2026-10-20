"use client";

import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

type Progress = {
  group: string;
  tables: { name: string; label: string; rows: number }[];
}[];

// 가상 데이터 생성 진행 화면: 데모 DB 표별 행 수를 2초마다 갱신
export default function DemoDbProgress() {
  const [data, setData] = useState<Progress>([]);
  const [updatedAt, setUpdatedAt] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const resp = await fetch(`${API_URL}/data/demo-progress`);
        if (!resp.ok) throw new Error(`서버 오류 (${resp.status})`);
        setData(await resp.json());
        setUpdatedAt(new Date().toLocaleTimeString("ko-KR"));
        setError("");
      } catch (e) {
        setError(e instanceof Error ? e.message : "불러오기 실패");
      }
    }
    load();
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  }, []);

  const all = data.flatMap((g) => g.tables);
  const total = all.reduce((sum, t) => sum + t.rows, 0);
  const filled = all.filter((t) => t.rows > 0).length;

  return (
    <div className="min-h-screen bg-canvas-soft">
      <header className="bg-primary px-8 py-6 text-white">
        <h1 className="text-[28px] leading-[1.14] font-medium tracking-[-0.63px]">가상 데이터 생성 현황</h1>
        <p className="mt-2 text-sm text-white/70">
          데모 DB(MES_DEMO) 표 {all.length}개 중 {filled}개 채워짐 · 전체 {total.toLocaleString()}행 · {updatedAt} 갱신
        </p>
      </header>

      {error && <p className="px-8 pt-4 text-sm text-red-600">{error}</p>}

      <main className="grid gap-6 p-8 md:grid-cols-2 xl:grid-cols-3">
        {data.map((g) => (
          <section key={g.group} className="rounded-lg border border-hairline bg-canvas p-5 shadow-card">
            <h2 className="mb-3 text-lg font-medium">{g.group}</h2>
            <ul className="space-y-2">
              {g.tables.map((t) => (
                <li key={t.name} className="flex items-center justify-between gap-3 text-sm">
                  <span className="min-w-0">
                    <span className="block truncate">{t.label}</span>
                    <span className="block text-[11px] text-ink-faint">{t.name}</span>
                  </span>
                  <span
                    className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${
                      t.rows > 0 ? "bg-teal-deep text-white" : "bg-canvas-soft text-ink-faint"
                    }`}
                  >
                    {t.rows.toLocaleString()}행
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </main>
    </div>
  );
}
