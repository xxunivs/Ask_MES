# 논문 실험 결과 (원본)

논문 "NeuroFactory: Ontology-Grounded Hybrid RAG for Natural Language Querying" 의 ablation 실험 원본 결과.
2026-06 실제 MES 개발 DB 에서 측정했고, 질문 세트는 `backend/data/benchmark/mes_nl2sql_gold_v3.jsonl` (200문항), LLM 은 Qwen3.5-9B.

| 구성 | 설명 | VS (%) | EX_exec (%) | EX_loose (%) | Table F1 |
|------|------|--------|-------------|--------------|----------|
| B0 | 스키마 요약만 | 100.0 | 37.0 | 38.5 | 0.740 |
| B1 | 벡터 검색 | 100.0 | 68.5 | 69.0 | 0.773 |
| B2 | 벡터 검색 + FK 경로 | 100.0 | 66.0 | 66.5 | 0.752 |
| B3 | 벡터 검색 + 개념 사전 | 100.0 | 80.0 | 80.5 | 0.913 |
| FULL | 벡터 검색 + 개념 사전 + FK 경로 | 100.0 | 89.5 | 90.5 | 0.898 |

1. VS: 생성한 SQL 이 유효한 SELECT 문인 비율
2. EX_exec: 정답 SQL 과 생성 SQL 이 모두 오류 없이 실행된 비율. 결과값 일치 여부는 보지 않음
3. Table F1: 생성 SQL 이 쓴 테이블과 정답 테이블의 일치도

파일
1. `ablation_summary.json`: 위 표의 원본
2. `run_<구성>_<시각>.csv`: 문항별 생성 SQL, 실행 성공 여부, 행 수. FULL 은 두 번 실행한 결과가 있음

공개 저장소의 데모 DB 는 가상 데이터라, 같은 구성으로 다시 돌려도 이 숫자와 같게 나오지 않는다.
