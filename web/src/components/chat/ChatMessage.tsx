import type { NlToSqlResponse } from "@/lib/api";
import AutoChart from "@/components/analysis/AutoChart";
import ResultTable from "./ResultTable";

// 대화 한 건
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
        className={`max-w-[85%] space-y-3 rounded-lg px-5 py-4 text-base ${
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

// SQL, 실행 결과 표와 차트
function QueryResult({ result }: { result: NlToSqlResponse }) {
  return (
    <>
      <p className="font-medium">{result.description}</p>
      <pre className="overflow-auto whitespace-pre-wrap rounded-md bg-primary-deep p-3 font-mono text-xs text-white/90">
        {result.sql}
      </pre>
      {result.data ? (
        <ResultTable data={result.data} />
      ) : (
        <p className="text-sm text-red-600">DB 실행 오류: {result.db_error}</p>
      )}
      {result.data && <AutoChart data={result.data} />}
    </>
  );
}
