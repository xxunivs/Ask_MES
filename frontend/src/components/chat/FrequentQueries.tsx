const QUESTIONS = [
  "홀드 상태인 LOT 목록 보여줘",
  "불량 유형별 불량 수량 보여줘",
  "월별 LOT 투입 수량 추이 보여줘",
  "제품 유형별 월별 LOT 수 추이 보여줘",
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
          className="rounded-full border border-control-line bg-gradient-to-b from-white to-[#f1f2f4] px-4 py-2 text-sm font-semibold shadow-[0_1px_2px_rgba(0,0,0,0.10),inset_0_1px_0_#fff] hover:border-[#9aa1ab] hover:to-[#e6e8eb] active:translate-y-px active:shadow-inner disabled:opacity-40"
        >
          {q}
        </button>
      ))}
    </div>
  );
}
