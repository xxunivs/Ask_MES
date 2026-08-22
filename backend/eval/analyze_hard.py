import csv, sys

path = sys.argv[1] if len(sys.argv) > 1 else "eval/results/run_FULL_20260614_232614.csv"
with open(path, encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

hard = [r for r in rows if r.get("difficulty") == "hard"]
print(f"=== hard 문항 ({len(hard)}개) ===\n")
for r in hard:
    ok = r.get("exec_ok", "")
    sv = r.get("schema_valid", "")
    print(f"[{r['id']}] exec={ok} schema_valid={sv}")
    print(f"  질문: {r['question']}")
    if ok != "True":
        print(f"  pred_sql  : {r.get('pred_sql','')[:200]}")
        print(f"  db_error  : {r.get('db_error','')[:200]}")
        print(f"  schema_err: {r.get('schema_error','')[:150]}")
    print()
