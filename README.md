<img src="img/hero.png" alt="Ask MES!">

# Ask MES!

자연어 질문을 SQL문으로 바꿔 MES(제조 실행 시스템) 데이터를 조회하는 NL2SQL 시스템

**데모: https://ask-mes.web.app** (실제 공장 데이터 대신 가상 데이터로 동작합니다)

| 기간 | 구분 | 맡은 역할 |
|------|------|------|
| 2026.03 ~ 2026.06 | 캡스톤디자인 팀 프로젝트, LS티라유텍 협업 | AI, BE, FE |

<br>

## 🎯 개요

SQL을 모르는 제조 현업이 **자연어로 질문하면 SQL로 바꿔 MES DB를 조회**하는 시스템을 개발했습니다.
절삭공구 공장 MES (19테이블, 457컬럼, 2.7억 행), 외부 API를 쓸 수 없는 온프레미스 환경이라 오픈 모델 Qwen3.5-9B를 사용했습니다.

#### 질문하면 SQL을 만들어 실행하고 표로 보여 줌

<img src="img/screen_table.png" alt="질문 결과 표">

#### 날짜, 숫자 결과는 차트로 전환

<img src="img/screen_chart.png" alt="질문 결과 차트">

**맡은 역할 (AI, BE, FE)**: 개념 사전 구축, 하이브리드 검색, JOIN 경로 계산, 실제 DB 값 확인, 웹 개발과 공개 데모 배포

<br>

## 📂 시스템 구조

질문이 들어오면 필요한 DB 정보를 찾아 LLM에 함께 넘기고, LLM이 만든 SQL을 검사한 뒤 조회만 가능한 계정으로 실행합니다.

<img src="img/architecture.png" alt="시스템 구조">

<br>

## 🔧 트러블 슈팅

| 문제 | 해결 | 코드 |
|------|------|------|
| **1. 질문에 맞는 테이블 찾기**<br>현장 용어('홀드')와 DB 이름(`ISHOLD`)이 달라 테이블을 못 찾음 | 현장 용어 155개 개념 사전과 벡터 검색을 합쳐 정답 테이블 적중률 100% | `backend/app/retrieval/retriever.py`<br>`backend/app/retrieval/ontology_loader.py`<br>`backend/data/mes_ontology.ttl` |
| **2. 테이블 사이 연결 경로 찾기**<br>직접 연결되지 않은 테이블은 LLM이 중간 테이블을 빠뜨림 | 외래키 그래프에서 Dijkstra로 JOIN 경로를 계산해 힌트로 제공, SQL 실행 성공률 80% → 89.5% | `backend/app/retrieval/fk_resolver.py` |
| **3. 컬럼 안의 실제 값 맞추기**<br>'Y', 'N' 컬럼을 `ISHOLD = TRUE`로 비교해 실행 오류 | 생성 전에 실제 값을 조회해 프롬프트에 넣어 `ISHOLD = 'Y'`로 생성 | `backend/app/sampling/live_sample.py` |

<br>

## 📊 결과

GOLD 질문 200개 기준 SQL 실행 성공률 **37.0% → 89.5%** (검색 없이 테이블 목록만 넣었을 때 대비), 정답 테이블 적중률 **100%**

- 논문 투고: NeuroFactory: Ontology-Grounded Hybrid RAG for Natural Language Querying in Manufacturing Execution Systems (IEEE BigData 2026, BD-SMDT 워크숍, 공동저자)
- 특허 출원: 사용자 정보를 이용한 자연어 질의 처리 장치 및 그 동작 방법 (10-2026-0182784, 2026.09.23)

<br>

## 🛠 사용 기술

<img src="img/stack.png" alt="사용 기술">

<br>

## 📁 폴더 구조

```
backend/
├── app/
│   ├── main.py                FastAPI 진입점
│   ├── pipeline.py            단계를 순서대로 호출
│   ├── config.py              설정값 (.env)
│   ├── routers/               웹 API (chat: 질문, data: 데이터 둘러보기)
│   ├── retrieval/             필요한 정보 찾기: retriever, ontology_loader(개념 사전), fk_resolver(JOIN 경로)
│   ├── sampling/              실제 값 확인: live_sample
│   ├── generation/            SQL 생성: prompts, llm, date_policy
│   ├── autofix/               자동 교정: sql_autofix
│   ├── validation/            검증: sql_validator, query_safety, code_values, concept_alignment
│   └── execution/             실행: sql_executor, sqlite_db, demo_db
├── data/                      스키마, 온톨로지, 코드값, 벤치마크 질문 세트, 데모용 SQLite DB
└── eval/                      벤치마크 실행, 채점, 논문 원본 결과

demo-db/                       데모 DB (가상 데이터) 테이블 정의, 생성 스크립트
web/                           웹 화면 (Next.js, React, TypeScript)
img/                           README 그림
hosting/                       ask-mes.web.app 연결 설정 (Firebase Hosting)
docker-compose.yml             데모 DB (SQL Server)
```
