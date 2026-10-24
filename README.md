# NeuroFactory

자연어 질문을 SQL로 바꿔 MES(제조실행시스템) DB를 조회하는 시스템

공개용 데모는 가상 데이터 기반으로 동작한다.

---

## 처리 흐름

`backend/app/pipeline.py` 의 `run_pipeline()` 한 함수에 순서대로 있다. 웹 API 와 벤치마크가 같은 함수를 쓴다. 오른쪽은 각 단계 코드가 있는 폴더(`backend/app/` 아래).

```
질문
 1. 관련 테이블 찾기   개념 사전(온톨로지) + 벡터 검색(bge-m3, ChromaDB)            retrieval/
 2. JOIN 경로 계산     FK 그래프 최단 경로(Dijkstra)                                retrieval/
 3. 실제 값 확인       찾은 테이블의 샘플 조회                                      sampling/
 4. SQL 생성           1~3 을 프롬프트에 넣어 LLM(Qwen3.5-9B) 호출                  generation/
 5. 자동 교정          확정적인 문법 오류를 코드로 수정                             autofix/
 6. 검증               스키마, 코드값, 안전성 검사, 실패 시 오류를 넣어 1회 재생성  validation/
 7. 실행               읽기 전용 계정으로 실행, 실패 시 DB 오류를 넣어 1회 재생성   execution/
결과 표
```

## 결과

같은 200문항(`backend/data/benchmark/mes_nl2sql_gold_v3.jsonl`), 실제 MES 개발 DB 기준.

| 시점 | VS (%) | EX_exec (%) | Table F1 |
|------|--------|-------------|----------|
| 논문 (2026-06) | 100.0 | 89.5 | 0.898 |
| 현재 코드 (2026-10-23) | 100.0 | 93.0 | 0.848 |

EX_exec 는 정답 SQL 과 생성 SQL 이 모두 오류 없이 실행된 비율이다. 결과값 일치 여부는 보지 않는다. 자세한 내용은 `backend/eval/paper_results/README.md`.

---

## 폴더

```
backend/
├── app/
│   ├── main.py                FastAPI 진입점
│   ├── pipeline.py            1~7단계를 순서대로 호출
│   ├── config.py              설정값 (.env)
│   ├── routers/               웹 API (chat: 질문, data: 데이터 둘러보기)
│   ├── retrieval/             1~2단계: retriever, ontology_loader(개념 사전), fk_resolver(JOIN 경로)
│   ├── sampling/              3단계: live_sample
│   ├── generation/            4단계: prompts, llm, date_policy
│   ├── autofix/               5단계: sql_autofix
│   ├── validation/            6단계: sql_validator, query_safety, code_values, concept_alignment
│   └── execution/             7단계: sql_executor, demo_db
├── data/                      스키마, 온톨로지, 코드값, 벤치마크 질문 세트
└── eval/                      벤치마크 실행, 채점, 논문 원본 결과

demo-db/                       데모 DB (가상 데이터) 테이블 정의, 생성 스크립트
web/                           웹 화면 (Next.js, React, TypeScript)
docker-compose.yml             데모 DB (SQL Server)
```

---

## 로컬 실행

Python 3.12, Node.js, Docker, Ollama(`qwen3.5:9b`, `bge-m3`) 필요.

```bash
# 1. 데모 DB
cp .env.example .env                                  # MSSQL_SA_PASSWORD 채우기
docker compose up -d
# demo-db/01_create_tables.sql, 02_create_reader.sql 실행 후
cd backend && ./venv/bin/python ../demo-db/generate_demo_data.py

# 2. 백엔드
cd backend
cp .env.example .env                                  # DEMO_DB_*, OLLAMA_URL 채우기
python3.12 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/uvicorn app.main:app --port 8001

# 3. 웹
cd web && npm install && npm run dev                  # http://localhost:3000
```

## 벤치마크

```bash
cd backend
./venv/bin/python eval/run_benchmark.py --preset FULL --execute
./venv/bin/python eval/score.py eval/results/latest.csv --by difficulty
```
