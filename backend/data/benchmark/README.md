# 평가 질문 세트

`mes_nl2sql_gold_v3.jsonl`: 자연어 질문과 정답 SQL 200쌍. 논문 본실험에 쓴 세트.

| 난이도 | 개수 | | 질문 유형 | 개수 | | JOIN 필요 | 개수 |
|---|---|---|---|---|---|---|---|
| easy | 80 | | list | 76 | | 아니요 | 129 |
| medium | 78 | | aggregate | 53 | | 예 | 71 |
| hard | 42 | | filter | 41 | | | |
| | | | timeseries | 30 | | | |

## 한 줄 형식

| 필드 | 설명 |
|------|------|
| `id` | 문항 ID (`Q001` ~ `Q200`) |
| `question` | 자연어 질문 |
| `gold_sql` | 정답 SELECT (MS SQL Server, `WITH (NOLOCK)`) |
| `tables` | 정답이 쓰는 테이블 (Table F1 채점용) |
| `concepts` | 질문에 나온 현장 개념 |
| `difficulty` | easy, medium, hard |
| `query_type` | list, filter, aggregate, timeseries |
| `requires_join` | JOIN 필요 여부 |

정답 SQL 의 날짜 조건은 "1년 전 기준"(`MES_DATE_MODE=dev_last_year`)으로 작성됐다.
