import csv, sys

path = sys.argv[1] if len(sys.argv) > 1 else "eval/results/run_FULL_merged.csv"
with open(path, encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

fails = [r for r in rows if r.get("exec_ok") != "True"]
print(f"실패: {len(fails)}문항\n")
for r in fails:
    print(f"[{r['id']}] {r['difficulty']} | schema={r.get('schema_valid')} | {r['question']}")
    print(f"  SQL : {r.get('pred_sql','')[:180]}")
    print(f"  err : {r.get('db_error','')[:120]}")
    print(f"  serr: {r.get('schema_error','')[:120]}")
    print()
