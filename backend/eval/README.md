# 성능 평가

질문 세트: `data/benchmark/mes_nl2sql_gold_v3.jsonl` (200문항, [설명](../data/benchmark/README.md))

## 실행 (backend/ 에서)

1. `python eval/run_benchmark.py --preset FULL --execute`: 200문항 실행, 결과는 `eval/results/run_FULL_<시각>.csv`
2. `python eval/score.py --by difficulty`: 마지막 결과 채점
3. `python eval/run_all_ablations.py --execute`: 구성 B0~FULL 을 차례로 실행하고 `report.py` 로 표 생성

LLM 서버와 DB 설정은 `.env` 를 따른다.

## 구성 (ablation)

| 구성 | 검색 방식 |
|------|-----------|
| B0 | 검색 없이 테이블 목록만 |
| B1 | 벡터 검색 |
| B2 | 벡터 검색 + FK 경로 |
| B3 | 벡터 검색 + 개념 사전 |
| FULL | 벡터 검색 + 개념 사전 + FK 경로 |

## 지표

1. VS: 유효한 SELECT 문 비율
2. EX_exec: 정답 SQL 과 생성 SQL 이 모두 오류 없이 실행된 비율 (결과값 일치는 보지 않음)
3. Table F1: 생성 SQL 이 쓴 테이블과 정답 테이블의 일치도

논문 원본 결과는 [paper_results](paper_results/README.md). 검증기 같은 결정적인 모듈의 테스트는 `tests/` 에서 `pytest` 로 돌린다.
