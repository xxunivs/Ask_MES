import {
  BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";

const COLORS = ["#3B82F6", "#EF4444", "#10B981", "#F59E0B", "#8B5CF6"];

/**
 * tableData: { columns: [...], rows: [[...]], count: N }  (2차원 배열 형식)
 *            ChatPage.normalizeTableData() 가 변환한 결과
 */
export default function StatisticsView({ sqlInfo, tableData }) {
  const hasData = tableData && tableData.columns?.length > 0 && tableData.rows?.length > 0;

  return (
    <div className="stats-view">
      {/* SQL 정보 */}
      <div className="stats-sql-info">
        <span className="stats-sql-label">실행된 SQL</span>
        <p className="stats-sql-desc">{sqlInfo?.description}</p>
        <details>
          <summary className="stats-sql-toggle">SQL 보기</summary>
          <pre className="stats-sql-code">{sqlInfo?.sql}</pre>
        </details>
      </div>

      {/* 원본 데이터 테이블 */}
      <div className="stats-raw-section">
        <h3 className="stats-raw-title">
          원본 데이터
          {hasData && (
            <span style={{ fontSize: "0.8em", fontWeight: "normal", marginLeft: 8, color: "#9ca3af" }}>
              ({tableData.count ?? tableData.rows.length}행)
            </span>
          )}
        </h3>

        {hasData ? (
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  {tableData.columns.map((col) => (
                    <th key={col}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tableData.rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, j) => (
                      <td key={j}>
                        {typeof cell === "number" ? cell.toLocaleString() : String(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="stats-hint" style={{ color: "#6b7280" }}>
            데이터가 없습니다. DB 연결 상태를 확인하세요.
          </p>
        )}
      </div>

      {/* 자동 차트: 숫자 컬럼이 2개 이상이면 막대 차트 자동 렌더링 */}
      {hasData && <AutoChart tableData={tableData} />}

      <p className="stats-hint">
        오른쪽 채팅에서 데이터에 대해 질문하면 Ollama가 분석해 드립니다.
      </p>
    </div>
  );
}

/** 실제 데이터로 자동 차트 생성 (숫자형 컬럼 감지) */
function AutoChart({ tableData }) {
  const { columns, rows } = tableData;
  if (!rows.length) return null;

  // 숫자형 컬럼 인덱스 감지
  const numericCols = columns.filter((_, ci) =>
    rows.slice(0, 5).every((row) => {
      const v = row[ci];
      return v !== "" && !isNaN(Number(v));
    })
  );
  // 문자형 컬럼 (label 후보)
  const strCols = columns.filter((c) => !numericCols.includes(c));

  if (numericCols.length === 0) return null;

  const labelCol = strCols[0] || columns[0];
  const labelIdx = columns.indexOf(labelCol);
  const numIdx = columns.indexOf(numericCols[0]);
  const numIdx2 = numericCols[1] ? columns.indexOf(numericCols[1]) : -1;

  // Recharts 용 데이터 변환 (최대 30행)
  const chartData = rows.slice(0, 30).map((row) => {
    const obj = { name: String(row[labelIdx] ?? "") };
    obj[numericCols[0]] = Number(row[numIdx]) || 0;
    if (numIdx2 >= 0) obj[numericCols[1]] = Number(row[numIdx2]) || 0;
    return obj;
  });

  // 파이 차트용 (첫 번째 숫자 컬럼, 최대 8개)
  const pieData = rows.slice(0, 8).map((row) => ({
    name: String(row[labelIdx] ?? ""),
    value: Number(row[numIdx]) || 0,
  }));

  return (
    <div className="stat-block">
      <div className="stat-block-header">
        <span className="stat-block-label">📊 자동 시각화</span>
      </div>
      <div className="stat-charts-row">
        {/* 막대 차트 */}
        <div className="stat-chart-card">
          <p className="stat-chart-title">{numericCols.slice(0, 2).join(" / ")} 비교</p>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#9ca3af" }} />
              <YAxis tick={{ fontSize: 10, fill: "#9ca3af" }} />
              <Tooltip
                contentStyle={{ background: "#1e293b", border: "none", borderRadius: 8, fontSize: 12 }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey={numericCols[0]} fill="#3B82F6" radius={[4, 4, 0, 0]} />
              {numericCols[1] && (
                <Bar dataKey={numericCols[1]} fill="#EF4444" radius={[4, 4, 0, 0]} />
              )}
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* 파이 차트 */}
        <div className="stat-chart-card">
          <p className="stat-chart-title">{numericCols[0]} 비율</p>
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie
                data={pieData}
                cx="50%"
                cy="50%"
                outerRadius={70}
                dataKey="value"
                label={({ name, percent }) =>
                  `${name} ${(percent * 100).toFixed(0)}%`
                }
                labelLine={false}
              >
                {pieData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{ background: "#1e293b", border: "none", borderRadius: 8, fontSize: 12 }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
