// ─── Frequent Queries (자주 입력된 채팅 예시) ───────────────────────────────
// count 기준 상위 항목을 홈 화면에 노출
export const frequentQueries = [
  { id: 1, text: "이번 주 생산량을 라인별로 보여줘", count: 42, category: "생산" },
  { id: 2, text: "오늘 불량률이 가장 높은 공정은?", count: 38, category: "품질" },
  { id: 3, text: "지난달 설비 가동률 추이를 알려줘", count: 31, category: "설비" },
  { id: 4, text: "작업자별 생산 실적을 비교해줘", count: 27, category: "작업자" },
  { id: 5, text: "이번 분기 납기 준수율은 얼마야?", count: 24, category: "납기" },
  { id: 6, text: "최근 7일간 불량 유형별 현황", count: 21, category: "품질" },
];

// ─── Mock SQL 변환 규칙 ────────────────────────────────────────────────────
export const nlToSqlMock = {
  "이번 주 생산량을 라인별로 보여줘": {
    sql: `SELECT
  work_date,
  line_name,
  produced_qty,
  defect_qty
FROM production_log
WHERE work_date BETWEEN DATE_TRUNC('week', CURRENT_DATE) AND CURRENT_DATE
ORDER BY work_date DESC, line_name;`,
    description: "이번 주 라인별 생산 원본 데이터",
  },
  "오늘 불량률이 가장 높은 공정은?": {
    sql: `SELECT
  work_date,
  process_name,
  produced_qty,
  defect_qty
FROM production_log
WHERE work_date = CURRENT_DATE
ORDER BY process_name;`,
    description: "오늘 공정별 생산 원본 데이터",
  },
  "지난달 설비 가동률 추이를 알려줘": {
    sql: `SELECT
  work_date,
  equipment_id,
  operation_time,
  planned_time
FROM equipment_log
WHERE work_date >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month')
  AND work_date < DATE_TRUNC('month', CURRENT_DATE)
ORDER BY work_date, equipment_id;`,
    description: "지난달 설비 가동 원본 데이터",
  },
  default: {
    sql: `SELECT
  work_date,
  line_name,
  produced_qty,
  defect_qty
FROM production_log
WHERE work_date >= CURRENT_DATE - INTERVAL '7 days'
ORDER BY work_date DESC, line_name;`,
    description: "최근 7일 라인별 생산 원본 데이터",
  },
};

// ─── Demo 테이블 데이터 (SQL 결과 시뮬레이션) ──────────────────────────────
export const demoTableData = {
  columns: ["라인명", "생산량", "불량수", "불량률(%)"],
  rows: [
    ["A라인", 1240, 18, 1.45],
    ["B라인", 980, 32, 3.27],
    ["C라인", 1105, 12, 1.09],
    ["D라인", 870, 45, 5.17],
    ["E라인", 1320, 9, 0.68],
  ],
};

// ─── Demo 차트 데이터 ─────────────────────────────────────────────────────
export const demoChartData = {
  barData: [
    { name: "A라인", 생산량: 1240, 불량수: 18 },
    { name: "B라인", 생산량: 980, 불량수: 32 },
    { name: "C라인", 생산량: 1105, 불량수: 12 },
    { name: "D라인", 생산량: 870, 불량수: 45 },
    { name: "E라인", 생산량: 1320, 불량수: 9 },
  ],
  lineData: [
    { date: "04-01", 가동률: 92.1 },
    { date: "04-02", 가동률: 88.4 },
    { date: "04-03", 가동률: 95.3 },
    { date: "04-04", 가동률: 91.7 },
    { date: "04-05", 가동률: 87.2 },
    { date: "04-06", 가동률: 93.8 },
    { date: "04-07", 가동률: 96.1 },
  ],
  pieData: [
    { name: "치수 불량", value: 38 },
    { name: "표면 불량", value: 27 },
    { name: "조립 불량", value: 19 },
    { name: "기타", value: 16 },
  ],
};

// ─── Demo 통계 요약 ───────────────────────────────────────────────────────
export const demoStats = {
  totalProduction: 5515,
  totalDefects: 116,
  avgDefectRate: 2.33,
  topLine: "E라인",
  worstLine: "D라인",
};

// ─── 분석 채팅 Mock 응답 ─────────────────────────────────────────────────
export const analysisMockResponses = {
  "불량률": "D라인의 불량률이 5.17%로 가장 높습니다. 전체 평균(2.33%) 대비 약 2.2배 높은 수치입니다. A라인(1.45%)과 비교하면 3.6배 차이가 납니다.",
  "생산량": "E라인이 1,320개로 가장 높은 생산량을 기록했으며, D라인이 870개로 가장 낮습니다. 전체 합계는 5,515개입니다.",
  "평균": "라인별 평균 생산량은 1,103개, 평균 불량률은 2.33%입니다.",
  "최고": "E라인이 생산량 1,320개, 불량률 0.68%로 가장 우수한 성과를 보이고 있습니다.",
  "최저": "D라인이 불량률 5.17%로 품질 면에서 가장 낮은 성과를 보이고 있습니다.",
  default: "해당 데이터를 분석한 결과, 전체 생산량은 5,515개이며 평균 불량률은 2.33%입니다. D라인의 불량률 개선이 가장 시급해 보입니다.",
};
