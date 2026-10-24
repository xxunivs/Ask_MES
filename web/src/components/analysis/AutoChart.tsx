"use client";

import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { QueryData } from "@/lib/api";

const COLORS = ["#1b1938", "#c9b4fa"];

function numericColumns(data: QueryData): string[] {
  return data.columns.filter((col) =>
    data.rows.slice(0, 5).every((row) => row[col] !== "" && row[col] !== null && !isNaN(Number(row[col]))),
  );
}

export function hasChart(data: QueryData): boolean {
  return data.rows.length > 0 && numericColumns(data).length > 0;
}

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
          {/* 막대 애니메이션 끔 (막대가 늦게 보이거나 안 보이는 현상 방지) */}
          <Bar dataKey={first} fill={COLORS[0]} isAnimationActive={false} />
          {second && <Bar dataKey={second} fill={COLORS[1]} isAnimationActive={false} />}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
