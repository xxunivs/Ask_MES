import type { TraceStep } from "@/lib/api";

// 처리 과정 보기
export default function TracePanel({ trace }: { trace: TraceStep[] }) {
  if (trace.length === 0) return null;

  return (
    <details className="text-sm">
      <summary className="cursor-pointer font-semibold text-primary underline">처리 과정 보기</summary>
      <div className="mt-2 space-y-1">
        {trace.map((t, i) => (
          <details key={i} className="ml-3">
            <summary className="cursor-pointer text-ink-mute hover:text-ink">{t.step}</summary>
            <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-all rounded-md border border-hairline bg-canvas-soft p-3 font-mono text-xs">
              {t.detail}
            </pre>
          </details>
        ))}
      </div>
    </details>
  );
}
