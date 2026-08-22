# MES NL→SQL 벤치마크 (골드 데이터셋)

논문 실험용 자연어 질의–골드 SQL 쌍입니다.

## 파일

| 파일 | 설명 |
|------|------|
| **`mes_nl2sql_gold_v2.jsonl`** | **50문항 (논문 본실험, 기본값)** |
| `mes_nl2sql_gold_v1.jsonl` | 20문항 파일럿 |
| `DATASET_INDEX.md` | 버전별 통계·개념 커버리지 |

## 레코드 스키마

| 필드 | 필수 | 설명 |
|------|------|------|
| `id` | ✓ | 문항 ID (`Q001` …) |
| `question` | ✓ | 한국어 자연어 질의 |
| `gold_sql` | ✓ | 정답 SELECT (MS SQL, `WITH (NOLOCK)`) |
| `tables` | ✓ | 참조 테이블 목록 (Table F1용) |
| `concepts` | | `mes_concept_map.json` 개념 태그 |
| `difficulty` | | `easy` / `medium` / `hard` |
| `query_type` | | `list` / `filter` / `aggregate` / `timeseries` |
| `requires_join` | | JOIN 필요 여부 |
| `notes` | | 검증·코드값 주의사항 |

## 골드 SQL 검증

```powershell
cd mes-llm-api
.\venv\Scripts\python -c "
import json
from pathlib import Path
for line in Path('data/benchmark/mes_nl2sql_gold_v1.jsonl').read_text(encoding='utf-8').splitlines():
    if line.strip():
        json.loads(line)
print('JSONL OK')
"
```

DB 연결 후 골드 SQL 실행 검증은 `eval/run_benchmark.py --gold-only` 를 사용하세요.

## 확장

- v3: 80~100문항 — `docs/db/procedures` StoredQuery 기반 추가
- `STATE`·코드값은 사이트(`SITEID`)별로 골드 SQL 재검증 후 갱신

### v1 → v2 변경

- Q001–Q020: v1 동일 유지
- Q021–Q050: 지연/확정 오더, 마스터 JOIN, 공정 라우팅, LOT-배치/자재, PM·알람, 시계열·복합 질의

## 실험 실행

```powershell
cd mes-llm-api
.\venv\Scripts\python eval\run_benchmark.py --preset FULL --dry-run
.\venv\Scripts\python eval\run_benchmark.py --preset B1 --execute
.\venv\Scripts\python eval\score.py eval\results\latest.csv
```

프리셋: `B0` | `B1` | `B2` | `B3` | `FULL` (→ `core.retriever.RetrievalConfig`)
