// 추천 질문 버튼

const QUESTIONS = [
  "홀드 상태인 LOT 목록 보여줘",
  "LOT ID와 제품명을 함께 보여줘",
  "불량 유형 목록 보여줘",
  "설비별 TrackIn 건수 추이를 일별로 보여줘",
];

export default function FrequentQueries({
  onSelect,
  disabled,
}: {
  onSelect: (question: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {QUESTIONS.map((q) => (
        <button
          key={q}
          onClick={() => onSelect(q)}
          disabled={disabled}
          className="rounded-full border border-hairline bg-canvas px-4 py-2 text-sm font-semibold hover:border-primary disabled:opacity-40"
        >
          {q}
        </button>
      ))}
    </div>
  );
}
