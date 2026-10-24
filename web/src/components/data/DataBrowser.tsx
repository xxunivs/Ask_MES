"use client";

import { useEffect, useRef, useState } from "react";
import { listTables, type TableGroup } from "@/lib/api";
import TableScreen from "./TableScreen";

export default function DataBrowser() {
  const [groups, setGroups] = useState<TableGroup[]>([]);
  const [selected, setSelected] = useState("CIM_LOT");
  const [error, setError] = useState("");

  useEffect(() => {
    listTables().then(setGroups).catch((e) => setError(e.message));
  }, []);

  const currentGroup = groups.find((g) => g.tables.some((t) => t.name === selected));
  const currentTable = currentGroup?.tables.find((t) => t.name === selected);

  return (
    <div className="flex h-full flex-col text-[12px] text-mes-ink">
      <div className="flex items-center gap-3 border-b border-panel-line bg-ribbon px-3 py-1.5">
        <TableMenu groups={groups} selected={selected} onSelect={setSelected}>
          <span className="text-mes-sub">{currentGroup?.group}</span>
          {currentGroup && <span className="mx-1.5 text-[#9aa1ab]">›</span>}
          <span className="font-bold">{currentTable?.label ?? selected}</span>
        </TableMenu>
        {error && <p className="text-mark">{error}</p>}
      </div>

      <div className="min-h-0 flex-1">
        <TableScreen key={selected} table={selected} />
      </div>
    </div>
  );
}

function TableMenu({
  groups,
  selected,
  onSelect,
  children,
}: {
  groups: TableGroup[];
  selected: string;
  onSelect: (name: string) => void;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [hovered, setHovered] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function close(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  function toggle() {
    const idx = groups.findIndex((g) => g.tables.some((t) => t.name === selected));
    setHovered(Math.max(idx, 0));
    setOpen((v) => !v);
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={toggle}
        className={`flex items-center gap-1 rounded-md border border-[#aeb4bd] bg-gradient-to-b from-white to-[#eef0f3] px-3 py-1 text-[13px] shadow-[0_1px_2px_rgba(0,0,0,0.12),inset_0_1px_0_#fff] hover:border-[#8c939d] hover:to-[#e2e5e9] active:shadow-inner ${
          open ? "border-link" : ""
        }`}
      >
        {children}
        <span className="ml-2 border-l border-[#cdd2d8] pl-2 text-[10px] text-mes-sub">▼</span>
      </button>

      {open && (
        <div className="absolute top-full left-0 z-30 mt-1 flex text-[13px]">
          <ul className="w-44 rounded-md border border-panel-line bg-white py-1 shadow-float">
            {groups.map((g, i) => (
              <li key={g.group}>
                <button
                  onMouseEnter={() => setHovered(i)}
                  onClick={() => setHovered(i)}
                  className={`flex w-full items-center justify-between px-3 py-1.5 text-left ${
                    i === hovered ? "bg-link text-white" : ""
                  }`}
                >
                  {g.group}
                  <span>›</span>
                </button>
              </li>
            ))}
          </ul>
          {groups[hovered] && (
            <ul className="-ml-px w-56 self-start rounded-md border border-panel-line bg-white py-1 shadow-float">
              {groups[hovered].tables.map((t) => (
                <li key={t.name}>
                  <button
                    onClick={() => {
                      onSelect(t.name);
                      setOpen(false);
                    }}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-link hover:text-white"
                  >
                    <span className="w-3 text-[11px]">{t.name === selected ? "✓" : ""}</span>
                    {t.label}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
