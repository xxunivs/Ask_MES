"use client";

import { useRef, useState } from "react";
import ChatPage from "@/components/chat/ChatPage";
import DataBrowser from "@/components/data/DataBrowser";

const MIN_CHAT = 320;
const MIN_DATA = 360;

// 왼쪽 데이터 둘러보기와 오른쪽 질문 화면, 가운데 경계선으로 넓이 조절
export default function Workspace() {
  const [chatWidth, setChatWidth] = useState(440);
  const [dragging, setDragging] = useState(false);
  const areaRef = useRef<HTMLDivElement>(null);

  function startDrag(e: React.PointerEvent<HTMLDivElement>) {
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragging(true);
  }

  function drag(e: React.PointerEvent<HTMLDivElement>) {
    if (!dragging || !areaRef.current) return;
    const rect = areaRef.current.getBoundingClientRect();
    const width = rect.right - e.clientX;
    setChatWidth(Math.min(Math.max(width, MIN_CHAT), rect.width - MIN_DATA));
  }

  return (
    <div className="flex h-screen flex-col bg-canvas-soft">
      <div ref={areaRef} className={`flex min-h-0 flex-1 ${dragging ? "cursor-col-resize select-none" : ""}`}>
        <section className="min-h-0 min-w-0 flex-1">
          <DataBrowser />
        </section>

        {/* 넓이 조절용 경계선 손잡이 */}
        <div
          role="separator"
          aria-orientation="vertical"
          title="끌어서 넓이 조절"
          onPointerDown={startDrag}
          onPointerMove={drag}
          onPointerUp={() => setDragging(false)}
          className={`group relative w-2 shrink-0 cursor-col-resize border-x border-hairline ${
            dragging ? "bg-violet-soft" : "bg-canvas-soft hover:bg-violet-soft"
          }`}
        >
          <span className="absolute top-1/2 left-1/2 flex -translate-x-1/2 -translate-y-1/2 flex-col gap-1">
            {[0, 1, 2].map((i) => (
              <span key={i} className="h-1 w-1 rounded-full bg-ink-faint group-hover:bg-primary" />
            ))}
          </span>
        </div>

        <section className="min-h-0 shrink-0" style={{ width: chatWidth }}>
          <ChatPage />
        </section>
      </div>
    </div>
  );
}
