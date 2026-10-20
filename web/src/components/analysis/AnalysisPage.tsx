"use client";

import { useState } from "react";
import { analyzeData, type NlToSqlResponse } from "@/lib/api";
import ChatInput from "@/components/chat/ChatInput";
import ResultTable from "@/components/chat/ResultTable";
import AutoChart from "./AutoChart";

type Note = { id: number; role: "user" | "assistant"; text: string };

// 분석 화면: 왼쪽 결과와 차트, 오른쪽 분석 질문
export default function AnalysisPage({ result }: { result: NlToSqlResponse }) {
  const [notes, setNotes] = useState<Note[]>([
    {
      id: 0,
      role: "assistant",
      text: `조회된 ${result.data?.count ?? 0}행에 대해 질문해 주세요. 예) 불량률이 가장 높은 항목은?`,
    },
  ]);
  const [loading, setLoading] = useState(false);

  async function handleSend(question: string) {
    setNotes((prev) => [...prev, { id: Date.now(), role: "user", text: question }]);
    setLoading(true);
    let answer: string;
    try {
      answer = await analyzeData(question, result.data);
    } catch (e) {
      answer = `오류: ${e instanceof Error ? e.message : "다시 시도해 주세요."}`;
    }
    setNotes((prev) => [...prev, { id: Date.now(), role: "assistant", text: answer }]);
    setLoading(false);
  }

  return (
    <div className="grid h-full gap-4 overflow-hidden p-4 md:grid-cols-[3fr_2fr]">
      <section className="space-y-4 overflow-y-auto">
        <div>
          <h2 className="text-[22px] leading-[1.1] font-normal tracking-[-0.315px]">{result.description}</h2>
          <details className="mt-1 text-xs">
            <summary className="cursor-pointer text-ink-mute underline">실행된 SQL</summary>
            <pre className="mt-1 whitespace-pre-wrap rounded-md bg-primary-deep p-3 font-mono text-white/90">{result.sql}</pre>
          </details>
        </div>
        {result.data && <ResultTable data={result.data} />}
        {result.data && <AutoChart data={result.data} />}
      </section>

      <section className="flex flex-col overflow-hidden rounded-lg border border-hairline bg-canvas shadow-card">
        <p className="border-b border-hairline px-4 py-3 text-sm font-semibold">데이터 질문</p>
        <div className="flex-1 space-y-2 overflow-y-auto p-4 text-sm">
          {notes.map((n) => (
            <p
              key={n.id}
              className={`whitespace-pre-wrap rounded px-3 py-2 ${
                n.role === "user" ? "ml-8 bg-primary text-white" : "mr-8 bg-canvas-soft"
              }`}
            >
              {n.text}
            </p>
          ))}
          {loading && <p className="text-ink-mute">분석 중...</p>}
        </div>
        <div className="border-t border-hairline p-3">
          <ChatInput onSend={handleSend} disabled={loading} />
        </div>
      </section>
    </div>
  );
}
