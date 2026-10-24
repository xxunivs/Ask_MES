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
          className="rounded-full border border-[#cfd3d9] bg-gradient-to-b from-white to-[#f1f2f4] px-4 py-2 text-sm font-semibold shadow-[0_1px_2px_rgba(0,0,0,0.10),inset_0_1px_0_#fff] hover:border-[#9aa1ab] hover:to-[#e6e8eb] active:translate-y-px active:shadow-inner disabled:opacity-40"
        >
          {q}
        </button>
      ))}
    </div>
  );
}
