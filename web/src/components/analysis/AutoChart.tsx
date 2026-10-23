"use client";

import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { QueryData } from "@/lib/api";

// design.md 팔레트 (indigo, violet)
const COLORS = ["#1b1938", "#c9b4fa"];

// 앞 5행이 모두 숫자인 칸
function numericColumns(data: QueryData): string[] {
  return data.columns.filter((col) =>
    data.rows.slice(0, 5).every((row) => row[col] !== "" && row[col] !== null && !isNaN(Number(row[col]))),
  );
}

// 차트로 그릴 숫자 칸이 있는지
export function hasChart(data: QueryData): boolean {
  return data.rows.length > 0 && numericColumns(data).length > 0;
}

// 숫자 칸을 막대 차트로 (최대 2개 칸, 30행)
export default function AutoChart({ data }: { data: QueryData }) {
  const numericCols = numericColumns(data);
  if (data.rows.length === 0 || numericCols.length === 0) return null;

  const labelCol = data.columns.find((c) => !numericCols.includes(c)) ?? data.columns[0];
  const [first, second] = numericCols;
  const barData = data.rows.slice(0, 30).map((row) => ({
    name: String(row[labelCol] ?? ""),
    [first]: Number(row[first]) || 0,
    ...(second ? { [second]: Number(row[second]) || 0 } : {}),
  }));

  return (
    <div className="rounded-md border border-hairline bg-canvas p-3">
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={barData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="name" tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey={first} fill={COLORS[0]} isAnimationActive={false} />
          {second && <Bar dataKey={second} fill={COLORS[1]} isAnimationActive={false} />}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
