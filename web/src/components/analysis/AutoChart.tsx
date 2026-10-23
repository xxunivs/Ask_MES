"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { QueryData } from "@/lib/api";

// design.md 팔레트 (indigo, violet, teal, warm grey)
const COLORS = ["#1b1938", "#c9b4fa", "#155555", "#0e3030", "#9a9794"];

// 숫자 컬럼을 찾아 막대, 원형 차트 자동 생성
export default function AutoChart({ data }: { data: QueryData }) {
  const { columns, rows } = data;
  if (rows.length === 0) return null;

  // 앞 5행이 모두 숫자인 컬럼
  const numericCols = columns.filter((col) =>
    rows.slice(0, 5).every((row) => row[col] !== "" && row[col] !== null && !isNaN(Number(row[col]))),
  );
  if (numericCols.length === 0) return null;

  const labelCol = columns.find((c) => !numericCols.includes(c)) ?? columns[0];
  const [first, second] = numericCols;

  const barData = rows.slice(0, 30).map((row) => ({
    name: String(row[labelCol] ?? ""),
    [first]: Number(row[first]) || 0,
    ...(second ? { [second]: Number(row[second]) || 0 } : {}),
  }));
  const pieData = rows.slice(0, 8).map((row) => ({
    name: String(row[labelCol] ?? ""),
    value: Number(row[first]) || 0,
  }));

  return (
    <div className="@container">
    <div className="grid gap-4 @2xl:grid-cols-2">
      <div className="rounded-lg border border-hairline bg-canvas p-4 shadow-card">
        <p className="mb-2 text-xs font-semibold">{numericCols.slice(0, 2).join(" / ")} 비교</p>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={barData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey={first} fill={COLORS[0]} />
            {second && <Bar dataKey={second} fill={COLORS[1]} />}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="rounded-lg border border-hairline bg-canvas p-4 shadow-card">
        <p className="mb-2 text-xs font-semibold">{first} 비율</p>
        <ResponsiveContainer width="100%" height={200}>
          <PieChart>
            <Pie data={pieData} dataKey="value" outerRadius={70} label={{ fontSize: 10 }}>
              {pieData.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
    </div>
  );
}
