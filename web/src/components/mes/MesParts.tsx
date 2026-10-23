// MES 화면 공통 부품: 조회 조건 칸, LIST 탭, 합계 줄

export function ConditionPanel({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-6 border-b border-panel-line bg-panel px-4 py-3">
      <div className="flex flex-1 flex-wrap items-center gap-x-8 gap-y-2">{children}</div>
      {action}
    </div>
  );
}

export function ConditionField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex items-center gap-2">
      <span className="text-[10px] text-mark">◇</span>
      <span className="w-16 font-bold">{label}</span>
      {children}
    </label>
  );
}

export function ListTab({ title = "LIST" }: { title?: string }) {
  return (
    <span className="mt-1 w-fit border border-b-0 border-panel-line bg-ribbon px-2 py-0.5 font-semibold">
      <span className="text-link">▦</span> {title}
    </span>
  );
}

export function GridFooter({
  page,
  from,
  count,
  canPrev,
  canNext,
  onFirst,
  onPrev,
  onNext,
  note,
}: {
  page: number;
  from: number;
  count: number;
  canPrev: boolean;
  canNext: boolean;
  onFirst: () => void;
  onPrev: () => void;
  onNext: () => void;
  note?: string;
}) {
  const arrow = "px-1 text-[#5c6168] disabled:opacity-30";
  return (
    <div className="flex items-center gap-1 border-x border-b border-panel-line bg-ribbon px-2 py-0.5">
      <button onClick={onFirst} disabled={!canPrev} className={arrow}>⏮</button>
      <button onClick={onPrev} disabled={!canPrev} className={arrow}>◀</button>
      <span className="bg-white px-2">합계 : {count}</span>
      <button onClick={onNext} disabled={!canNext} className={arrow}>▶</button>
      <span className="ml-3 text-[#5c6168]">
        {count ? `${from} - ${from + count - 1}` : "-"} / 페이지 {page}
      </span>
      {note && <span className="ml-auto text-[#5c6168]">{note}</span>}
    </div>
  );
}
