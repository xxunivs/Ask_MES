"use client";

import type { NlToSqlResponse } from "@/lib/api";
import { useState } from "react";
import AutoChart, { hasChart } from "@/components/analysis/AutoChart";
import ResultTable from "./ResultTable";

export type Message =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "assistant"; text: string }
  | { id: number; role: "assistant"; loading: true }
  | { id: number; role: "assistant"; result: NlToSqlResponse };

export default function ChatMessage({ message }: { message: Message }) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`${"result" in message ? "w-full" : "max-w-[85%]"} min-w-0 space-y-3 rounded-lg px-5 py-4 text-base ${
          isUser
            ? "bg-gradient-to-b from-[#2e2b55] to-primary text-white shadow-[0_2px_6px_rgba(27,25,56,0.25)]"
            : "border border-hairline bg-canvas shadow-[0_2px_8px_rgba(0,0,0,0.08)]"
        }`}
      >
        {"text" in message && <p className="whitespace-pre-wrap">{message.text}</p>}
        {"loading" in message && <p className="text-ink-mute">SQL을 만들고 있습니다...</p>}
        {"result" in message && <QueryResult result={message.result} />}
      </div>
    </div>
  );
}

function QueryResult({ result }: { result: NlToSqlResponse }) {
  const [view, setView] = useState<"table" | "chart">("table");
  if (!result.data) {
    return <p className="text-sm text-red-600">DB 실행 오류: {result.db_error}</p>;
  }
  const chartable = hasChart(result.data);

  return (
    <>
      {chartable && (
        <div className="inline-flex rounded-md border border-hairline bg-canvas-soft p-0.5 text-xs">
          {(["table", "chart"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`rounded px-3 py-1 ${view === v ? "bg-white font-semibold shadow-sm" : "text-ink-mute"}`}
            >
              {v === "table" ? "표" : "차트"}
            </button>
          ))}
        </div>
      )}
      {view === "chart" && chartable ? <AutoChart data={result.data} /> : <ResultTable data={result.data} />}
    </>
  );
}
