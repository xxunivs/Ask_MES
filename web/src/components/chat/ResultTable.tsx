import type { QueryData } from "@/lib/api";

// 조회 결과 표
export default function ResultTable({ data }: { data: QueryData }) {
  if (data.rows.length === 0) {
    return <p className="text-sm text-ink-mute">조회 결과가 없습니다.</p>;
  }

  return (
    <div className="max-h-80 overflow-auto rounded-md border border-hairline">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-canvas-soft text-ink-mute">
          <tr>
            {data.columns.map((col) => (
              <th key={col} className="px-3 py-2 font-semibold">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, i) => (
            <tr key={i} className="border-t border-hairline">
              {data.columns.map((col) => (
                <td key={col} className="px-3 py-1.5">
                  {String(row[col] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="border-t border-hairline px-3 py-1.5 text-xs text-ink-mute">{data.count}행</p>
    </div>
  );
}
