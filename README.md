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

### 1. 질문에 맞는 테이블 찾기

<img src="img/ts1_retrieval.png" alt="개념 사전과 벡터 검색" width="560">

**상황**
자연어 질문을 SQL로 변환하려면 먼저 관련 테이블과 컬럼을 정확하게 찾아야 했습니다. 그러나 현장에서는 '홀드', '보류'라는 표현을 사용하는 반면, DB에는 `CIM_LOT.ISHOLD`로 정의되어 있어 용어 간 불일치가 발생했습니다. 전체 457개 컬럼을 프롬프트에 모두 제공하는 방식은 컨텍스트 길이 한계로 어려웠습니다.

**해결**
현장 용어 155개를 DB 컬럼에 매핑한 개념 사전과 ChromaDB 기반 벡터 검색을 결합했습니다. 명확하게 대응되는 용어는 사전으로 검색하고, 다양한 자연어 표현은 의미 기반 검색으로 보완했습니다. 이를 통해 질문과 관련된 스키마만 선별해 LLM에 전달했으며, 정답 테이블 적중률 100%를 달성했습니다.

| 개념 사전만 | 벡터 검색만 | 둘 다 쓰면 |
|:---:|:---:|:---:|
| 88% | 96% | **100%** |

**배운 점**
LLM에 많은 스키마 정보를 제공하는 것만으로는 정확한 검색을 보장할 수 없었습니다. 도메인 용어의 특성에 따라 검색 방식을 구분하고, 질문에 필요한 정보를 선별해 전달하는 과정이 중요하다는 것을 배웠습니다.

### 2. 테이블 사이 연결 경로 찾기

<img src="img/ts2_join.png" alt="외래키 그래프로 JOIN 경로 계산" width="560">

**상황**
MES 데이터는 여러 테이블에 분산되어 있어 하나의 질문에 답하기 위해 다중 테이블 JOIN이 필요한 경우가 많았습니다. 특히 '설비 종류별 불량 수량'처럼 필요한 테이블이 직접 연결되어 있지 않으면, LLM이 중간에 거쳐야 할 테이블을 찾지 못해 SQL 생성에 실패했습니다.

**해결**
DB의 외래키(FK) 관계를 그래프로 구성하고, Dijkstra 알고리즘을 활용해 테이블 간 최단 연결 경로를 탐색하도록 구현했습니다. 이를 통해 중간 테이블을 포함한 JOIN 경로를 자동으로 계산하고, LLM에 힌트로 제공했습니다. 그 결과 SQL 실행 성공률을 80%에서 89.5%로 개선했습니다.

| JOIN 힌트 없이 | JOIN 힌트 추가 |
|:---:|:---:|
| 80.0% | **89.5%** |

**배운 점**
테이블 간 연결 관계는 DB에 이미 정의된 정보이므로, LLM이 매번 추론하도록 할 필요가 없었습니다. 정해진 규칙에 따라 계산할 수 있는 작업은 코드로 처리하고, LLM은 자연어 해석과 SQL 생성에 집중하도록 역할을 분리하는 것이 효과적임을 확인했습니다.

### 3. 컬럼 안의 실제 값 맞추기

<img src="img/ts3_values.png" alt="실제 값을 조회해 프롬프트에 넣음" width="560">

**상황**
테이블과 컬럼을 정확하게 찾아도 실제 데이터의 저장 형식을 잘못 해석해 SQL 실행에 실패하는 문제가 발생했습니다. 예를 들어 `ISHOLD` 컬럼에는 'Y', 'N'이 문자로 저장되어 있지만, LLM은 컬럼명만 보고 Boolean 타입으로 판단해 `ISHOLD = TRUE`와 같은 잘못된 조건을 생성했습니다.

**해결**
SQL 생성 전에 대상 컬럼의 샘플 데이터와 값 분포를 DB에서 조회하고, 이를 프롬프트에 함께 제공하도록 개선했습니다. LLM이 컬럼명뿐 아니라 실제 저장된 값의 형식을 참고하도록 하여, `ISHOLD = 'Y'`와 같이 데이터 형식에 맞는 조건을 생성할 수 있도록 했습니다.

| 전 | 후 |
|:---:|:---:|
| `ISHOLD = TRUE` (실행 오류) | `ISHOLD = 'Y'` (**실행 성공**) |

**배운 점**
초기에는 오류가 발생할 때마다 프롬프트에 예외 규칙을 추가했지만, 컬럼마다 다른 규칙을 관리하는 데 한계가 있었습니다. 실제 데이터를 조회하는 단계를 추가하면서 개별 오류에 대응하는 대신, 같은 원인으로 발생하는 오류를 공통적으로 줄일 수 있는 구조를 마련했습니다.

<br>

## 📊 결과

실제 MES DB로 직접 만든 GOLD 질문 200개(쉬움 80, 보통 78, 어려움 42)로 측정했습니다.

| 난이도 | 질문 | 정답 SQL |
|------|------|------|
| 쉬움 | LOT 목록 100건 보여줘 | `SELECT TOP 100 LOTID, SITEID, LOTNAME, STATE, QTY FROM CIM_LOT` |
| 보통 | 설비 유형별 설비 수를 보여줘 | `SELECT E.EQUIPMENTCLASSID, COUNT(*) FROM CIM_EQUIPMENT E LEFT JOIN CIM_EQUIPMENTCLASS C ON ... GROUP BY ...` |
| 어려움 | 설비별 Track In 건수 추이를 일별로 보여줘 | `SELECT CONVERT(date, TRACKINTIME), EQUIPMENTID, COUNT(*) FROM CIM_LOT WHERE TRACKINTIME >= ... GROUP BY ...` |

| SQL 실행 성공률 | 정답 테이블 적중률 |
|:---:|:---:|
| 37.0% → **89.5%** | **100%** |
| 검색 없이 테이블 목록만 넣었을 때 대비 | 벡터 검색만 96%, 개념 사전만 88% |

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
