"use client";

import { useState } from "react";
import type { NlToSqlResponse } from "@/lib/api";
import ChatPage from "@/components/chat/ChatPage";
import AnalysisPage from "@/components/analysis/AnalysisPage";
import DataBrowser from "@/components/data/DataBrowser";

type Tab =
  | { id: number; type: "chat"; label: string }
  | { id: number; type: "data"; label: string }
  | { id: number; type: "analysis"; label: string; result: NlToSqlResponse };

// 채팅 탭과 분석 탭 전환
export default function Workspace() {
  const [tabs, setTabs] = useState<Tab[]>([{ id: 0, type: "chat", label: "채팅" }]);
  const [activeId, setActiveId] = useState(0);

  function openAnalysis(result: NlToSqlResponse) {
    const id = Date.now();
    const label = result.description.slice(0, 15) || "분석";
    setTabs((prev) => [...prev, { id, type: "analysis", label, result }]);
    setActiveId(id);
  }

  function addChat() {
    const id = Date.now();
    setTabs((prev) => [...prev, { id, type: "chat", label: "새 채팅" }]);
    setActiveId(id);
  }

  function openData() {
    const existing = tabs.find((t) => t.type === "data");
    if (existing) return setActiveId(existing.id);
    const id = Date.now();
    setTabs((prev) => [...prev, { id, type: "data", label: "데이터 둘러보기" }]);
    setActiveId(id);
  }

  function closeTab(id: number) {
    const next = tabs.filter((t) => t.id !== id);
    setTabs(next);
    if (activeId === id) setActiveId(next[next.length - 1].id);
  }

  return (
    <div className="flex h-screen flex-col bg-canvas-soft">
      <nav className="flex items-center gap-2 bg-primary px-6 py-3 text-white">
        <span className="mr-4 text-base font-medium tracking-tight">NeuroFactory</span>
        {tabs.map((tab) => (
          <div
            key={tab.id}
            className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-sm ${
              tab.id === activeId ? "bg-violet-soft text-primary" : "text-white/70 hover:text-white"
            }`}
          >
            <button onClick={() => setActiveId(tab.id)}>
              {tab.type === "analysis" ? "📊 " : tab.type === "data" ? "🗂 " : ""}
              {tab.label}
            </button>
            {tabs.length > 1 && (
              <button onClick={() => closeTab(tab.id)} className="opacity-60 hover:opacity-100">
                ×
              </button>
            )}
          </div>
        ))}
        <button onClick={addChat} className="px-2 text-lg text-white/70 hover:text-white" title="새 채팅 탭">
          +
        </button>
        <button
          onClick={openData}
          className="ml-auto rounded-full bg-violet-soft px-4 py-1.5 text-sm font-semibold text-primary"
        >
          데이터 둘러보기
        </button>
      </nav>

      {/* 탭을 숨기기만 해서 전환해도 대화 기록 유지 */}
      {tabs.map((tab) => (
        <div key={tab.id} hidden={tab.id !== activeId} className="min-h-0 flex-1">
          {tab.type === "chat" && <ChatPage onAnalyze={openAnalysis} />}
          {tab.type === "analysis" && <AnalysisPage result={tab.result} />}
          {tab.type === "data" && <DataBrowser />}
        </div>
      ))}
    </div>
  );
}
