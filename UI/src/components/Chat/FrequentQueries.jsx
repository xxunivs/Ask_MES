import { frequentQueries } from "../../data/mockData";

const categoryColors = {
  생산: "bg-blue-100 text-blue-700 border-blue-200",
  품질: "bg-red-100 text-red-700 border-red-200",
  설비: "bg-green-100 text-green-700 border-green-200",
  작업자: "bg-purple-100 text-purple-700 border-purple-200",
  납기: "bg-orange-100 text-orange-700 border-orange-200",
};

// count 기준 상위 N개만 표시
const TOP_N = 6;

export default function FrequentQueries({ onSelect }) {
  const top = [...frequentQueries]
    .sort((a, b) => b.count - a.count)
    .slice(0, TOP_N);

  return (
    <div className="frequent-queries">
      <p className="fq-label">
        <span className="fq-icon">⚡</span> 자주 묻는 질문
      </p>
      <div className="fq-grid">
        {top.map((q) => (
          <button
            key={q.id}
            className={`fq-chip ${categoryColors[q.category] || "bg-gray-100 text-gray-700 border-gray-200"}`}
            onClick={() => onSelect(q.text)}
            title={`${q.count}회 사용됨`}
          >
            <span className="fq-category">{q.category}</span>
            <span className="fq-text">{q.text}</span>
            <span className="fq-count">{q.count}회</span>
          </button>
        ))}
      </div>
    </div>
  );
}
