import { useState } from "react";
import { X, MessageSquare, BarChart2, Plus } from "lucide-react";
import ChatPage from "./components/Chat/ChatPage";
import AnalysisPage from "./components/Analysis/AnalysisPage";
import "./App.css";

let tabIdCounter = 1;

export default function App() {
  const [tabs, setTabs] = useState([
    { id: 0, type: "chat", label: "새 채팅", sqlInfo: null },
  ]);
  const [activeTab, setActiveTab] = useState(0);

  /**
   * sqlMsg: { sql, description, data: { columns, rows, count } | null, ... }
   * data 를 포함하여 분석 탭에 전달
   */
  function handleSqlConfirmed(sqlMsg) {
    const newId = tabIdCounter++;
    const shortDesc = sqlMsg.description?.slice(0, 15) || "분석";
    setTabs((prev) => [
      ...prev,
      {
        id: newId,
        type: "analysis",
        label: shortDesc,
        sqlInfo: {
          sql: sqlMsg.sql,
          description: sqlMsg.description,
          data: sqlMsg.data || null,  // 실제 DB 데이터
        },
      },
    ]);
    setActiveTab(newId);
  }

  function closeTab(e, tabId) {
    e.stopPropagation();
    setTabs((prev) => {
      const next = prev.filter((t) => t.id !== tabId);
      if (activeTab === tabId && next.length > 0) {
        setActiveTab(next[next.length - 1].id);
      }
      return next;
    });
  }

  function addChatTab() {
    const newId = tabIdCounter++;
    setTabs((prev) => [
      ...prev,
      { id: newId, type: "chat", label: "새 채팅", sqlInfo: null },
    ]);
    setActiveTab(newId);
  }

  const active = tabs.find((t) => t.id === activeTab);

  return (
    <div className="app">
      {/* 탭 바 */}
      <div className="tab-bar">
        <div className="tab-bar-inner">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={`tab-btn ${activeTab === tab.id ? "active" : ""} ${tab.type === "analysis" ? "analysis-tab" : ""}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.type === "chat" ? (
                <MessageSquare size={13} />
              ) : (
                <BarChart2 size={13} />
              )}
              <span className="tab-label">{tab.label}</span>
              {tabs.length > 1 && (
                <span className="tab-close" onClick={(e) => closeTab(e, tab.id)}>
                  <X size={11} />
                </span>
              )}
            </button>
          ))}
          <button className="tab-add-btn" onClick={addChatTab} title="새 채팅 탭">
            <Plus size={15} />
          </button>
        </div>
      </div>

      {/* 콘텐츠 */}
      <div className="tab-content">
        {active?.type === "chat" && (
          <ChatPage key={active.id} onSqlConfirmed={handleSqlConfirmed} />
        )}
        {active?.type === "analysis" && (
          <AnalysisPage key={active.id} sqlInfo={active.sqlInfo} />
        )}
      </div>
    </div>
  );
}
