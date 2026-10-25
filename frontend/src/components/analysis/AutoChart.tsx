"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { QueryData } from "@/lib/api";

const COLORS = ["#1b1938", "#7c6cf0", "#2bb3a3", "#f2a516", "#e8607a"];
const MAX_SERIES = 5;
const MAX_BARS = 15;

type Row = Record<string, string | number>;

function numericColumns(data: QueryData): string[] {
  return data.columns.filter((col) =>
    data.rows.slice(0, 5).every((row) => row[col] !== "" && row[col] !== null && !isNaN(Number(row[col]))),
  );
}

function isDateColumn(data: QueryData, col: string): boolean {
  return data.rows.slice(0, 5).every((row) => /^\d{4}-\d{2}(-\d{2})?/.test(String(row[col] ?? "")));
}

export function hasChart(data: QueryData): boolean {
  return data.rows.length > 0 && numericColumns(data).length > 0;
}

// 긴 표(날짜, 항목, 값) -> 항목별 열 (대소문자만 다른 항목은 합침)
function pivot(data: QueryData, xCol: string, groupCol: string, valueCol: string) {
  const labels = new Map<string, string>();
  const keyOf = (row: Record<string, unknown>) => {
    const raw = String(row[groupCol] ?? "").trim();
    const key = raw.toUpperCase();
    if (!labels.has(key)) labels.set(key, raw || "(없음)");
    return key;
  };
  const totals = new Map<string, number>();
  for (const row of data.rows) {
    const key = keyOf(row);
    totals.set(key, (totals.get(key) ?? 0) + (Number(row[valueCol]) || 0));
  }
  const keys = [...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, MAX_SERIES).map(([k]) => k);
  const series = keys.map((k) => labels.get(k)!);
  const byX = new Map<string, Row>();
  for (const row of data.rows) {
    const key = keyOf(row);
    if (!keys.includes(key)) continue;
    const label = labels.get(key)!;
    const x = String(row[xCol] ?? "");
    const point = byX.get(x) ?? { name: x };
    point[label] = (Number(point[label]) || 0) + (Number(row[valueCol]) || 0);
    byX.set(x, point);
  }
  const points = [...byX.values()].sort((a, b) => String(a.name).localeCompare(String(b.name)));
  for (const point of points) for (const label of series) point[label] ??= 0;
  return { points, series };
}

function buildChart(data: QueryData) {
  const numericCols = numericColumns(data);
  const labelCols = data.columns.filter((c) => !numericCols.includes(c));
  const dateCol = labelCols.find((c) => isDateColumn(data, c));

  const xCol = dateCol ?? labelCols[0];
  const xRepeats = new Set(data.rows.map((row) => String(row[xCol] ?? ""))).size < data.rows.length;
  if (labelCols.length >= 2 && numericCols.length >= 1 && xRepeats) {
    const groupCol = labelCols.find((c) => c !== xCol)!;
    const { points, series } = pivot(data, xCol, groupCol, numericCols[0]);
    return { kind: dateCol ? "line" : "bar", points, series } as const;
  }

  const labelCol = xCol ?? data.columns[0];
  const series = numericCols.filter((c) => c !== labelCol).slice(0, 2);
  let points: Row[] = data.rows.map((row) => {
    const point: Row = { name: String(row[labelCol] ?? "") };
    for (const s of series) point[s] = Number(row[s]) || 0;
    return point;
  });
  if (dateCol) {
    points.sort((a, b) => String(a.name).localeCompare(String(b.name)));
    return { kind: "line", points, series } as const;
  }
  if (points.length > MAX_BARS) {
    points = [...points].sort((a, b) => Number(b[series[0]]) - Number(a[series[0]])).slice(0, MAX_BARS);
  }
  return { kind: "bar", points, series } as const;
}

export default function AutoChart({ data }: { data: QueryData }) {
  if (!hasChart(data)) return null;
  const { kind, points, series } = buildChart(data);
  if (series.length === 0) return null;

  const axis = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke="#e3e5e9" />
      {kind === "bar" ? (
        <XAxis dataKey="name" tick={{ fontSize: 10 }} interval={0} angle={-35} textAnchor="end" height={56} />
      ) : (
        <XAxis dataKey="name" tick={{ fontSize: 10 }} minTickGap={12} />
      )}
      <YAxis tick={{ fontSize: 10 }} width={36} />
      <Tooltip />
      {series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
    </>
  );

  return (
    <div className="rounded-md border border-hairline bg-canvas p-3">
      <ResponsiveContainer width="100%" height={240}>
        {kind === "line" ? (
          <LineChart data={points}>
            {axis}
            {series.map((s, i) => (
              <Line
                key={s}
                type="monotone"
                dataKey={s}
                stroke={COLORS[i % COLORS.length]}
                strokeWidth={2}
                dot={points.length <= 15}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        ) : (
          <BarChart data={points} margin={{ left: 24, right: 8 }}>
            {axis}
            {/* 애니메이션 끔 (막대가 늦게 보이는 현상) */}
            {series.map((s, i) => (
              <Bar key={s} dataKey={s} fill={COLORS[i % COLORS.length]} radius={[3, 3, 0, 0]} isAnimationActive={false} />
            ))}
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
