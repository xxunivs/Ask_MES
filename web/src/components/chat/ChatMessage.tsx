import type { NlToSqlResponse } from "@/lib/api";
import ResultTable from "./ResultTable";
import TracePanel from "./TracePanel";

// 대화 한 건
export type Message =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "assistant"; text: string }
  | { id: number; role: "assistant"; loading: true }
  | { id: number; role: "assistant"; result: NlToSqlResponse };

export default function ChatMessage({
  message,
  onAnalyze,
}: {
  message: Message;
  onAnalyze: (result: NlToSqlResponse) => void;
}) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] space-y-3 rounded-lg px-5 py-4 text-base ${
          isUser ? "bg-primary text-white" : "border border-hairline bg-canvas shadow-card"
        }`}
      >
        {"text" in message && <p className="whitespace-pre-wrap">{message.text}</p>}
        {"loading" in message && <p className="text-ink-mute">SQL을 만들고 있습니다...</p>}
        {"result" in message && <QueryResult result={message.result} onAnalyze={onAnalyze} />}
      </div>
    </div>
  );
}

// SQL, 실행 결과, 처리 과정
function QueryResult({
  result,
  onAnalyze,
}: {
  result: NlToSqlResponse;
  onAnalyze: (result: NlToSqlResponse) => void;
}) {
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
      <TracePanel trace={result.trace} />
      {result.data && result.data.rows.length > 0 && (
        <button
          onClick={() => onAnalyze(result)}
          className="rounded-md border border-hairline-dark bg-canvas px-4 py-2 text-sm font-semibold hover:bg-canvas-soft"
        >
          📊 분석 탭에서 보기
        </button>
      )}
    </>
  );
}
