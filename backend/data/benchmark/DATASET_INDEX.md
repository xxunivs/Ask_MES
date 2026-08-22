# 벤치마크 데이터셋 인덱스

| 버전 | 파일 | 문항 수 | 용도 |
|------|------|---------|------|
| v1 | `mes_nl2sql_gold_v1.jsonl` | 20 | 파일럿·스모크 테스트 |
| **v2** | **`mes_nl2sql_gold_v2.jsonl`** | **50** | **논문 본실험 (권장)** |

## v2 구성 (50문항)

| 난이도 | 문항 ID | 개수 |
|--------|---------|------|
| easy | Q001–Q003, Q005, Q007–Q011, Q014–Q015, Q017, Q021–Q022, Q027, Q031–Q033, Q035, Q038, Q042–Q043 | 22 |
| medium | Q004, Q006, Q012–Q013, Q016, Q018–Q019, Q023–Q026, Q028–Q030, Q034, Q036–Q037, Q039–Q041, Q044–Q046 | 22 |
| hard | Q020, Q047–Q050 | 6 |

| query_type | 개수 |
|------------|------|
| list | 18 |
| filter | 14 |
| aggregate | 14 |
| timeseries | 4 |

| requires_join | 개수 |
|---------------|------|
| false | 32 |
| true | 18 |

## 개념 커버리지 (v2 신규 Q021–Q050)

- 작업지시: 지연·확정 (Q021–Q022)
- 마스터 JOIN: 품목구분·제품명·자재명 (Q023–Q024, Q044)
- 공정 라우팅: 정의·경로·자동디스패치·노드-세그먼트 (Q025, Q037–Q039, Q048)
- LOT 관계: 배치·자재소비 (Q027–Q029)
- 설비: 알람·PM (Q031–Q032)
- 시계열·복합: 월별 TrackIn, 홀드+불량 TOP (Q049–Q050)

## 실행

```powershell
.\venv\Scripts\python eval\run_benchmark.py --gold data/benchmark/mes_nl2sql_gold_v2.jsonl --preset FULL --execute
.\venv\Scripts\python eval\score.py eval\results\latest.csv --by difficulty
```
