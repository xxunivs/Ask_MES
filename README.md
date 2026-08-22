# NeuroFactory

자연어 질문을 SQL로 바꿔 MES(제조실행시스템) DB를 조회하는 시스템

---

## 구성

```
NeuroFactory/
├── backend/          FastAPI 서버 (NL→SQL 파이프라인)
├── UI/               React + Vite 웹 화면
├── deploy/gcp/       Google Cloud 배포 메모, vLLM 서버 설정
├── docs/             특허·논문 자료, 시연 영상 (로컬 전용, git 제외)
└── README.md
```

### backend/

```
backend/
├── app/                       서버가 실행하는 코드 전부
│   ├── main.py                FastAPI 진입점 (기동 시 ChromaDB 시딩)
│   ├── core/
│   │   ├── config.py          .env 값 로딩
│   │   ├── llm.py             LLM 호출 (Ollama / vLLM 전환)
│   │   ├── sql_executor.py    생성된 SQL을 MES API 로 보내 실행
│   │   ├── retriever.py       ChromaDB 검색 — 질문에 맞는 테이블 선별
│   │   ├── ontology_loader.py 온톨로지 기반 개념어 인식, JOIN 힌트 추출
│   │   ├── fk_resolver.py     FK 그래프 + Dijkstra 최단 JOIN 경로 계산
│   │   ├── live_sample.py     실 DB 샘플 조회로 컨텍스트 보강, SQL 검증
│   │   └── term_resolver.py   모호어 해석 — 역할·맥락 기반 컬럼 선택
│   └── routers/
│       └── chat.py            API 엔드포인트, 프롬프트, SQL 재시도 루프
│
├── data/                      코드가 읽어들이는 입력 데이터
│   ├── mes_schema.json        MES 테이블·컬럼·FK 정의. 모든 모듈의 기준 파일
│   │                          ※ 바뀌면 서버 재시작 시 자동 재시딩
│   ├── mes_ontology.ttl       개념어 ↔ 테이블 매핑, JOIN 조건 (OWL/Turtle)
│   └── mes_concept_map.json   온톨로지 로딩 실패 시 쓰는 폴백 매핑
│
├── chroma_db/                 벡터 DB (기동 시 자동 생성, 삭제해도 재시딩됨)
├── convert_ontology.py        온톨로지 JSON → data/mes_schema.json 변환 도구
├── Dockerfile                 배포 시 이 폴더에서 빌드
├── requirements.txt
├── .env                       환경 설정 (git 제외)
└── .env.example
```

네 층으로 나뉩니다.

```
convert_ontology.py  →  data/  →  chroma_db/  →  app/ 이 사용
    (생성 도구)         (입력)     (자동 생성)      (실행 코드)
```

`Dockerfile`, `requirements.txt`, `.env` 는 그 바깥의 설정입니다.

### UI/

```
UI/src/
├── main.jsx / App.jsx         진입점, 채팅·분석 페이지 전환
├── components/Chat/           ChatPage, ChatMessage, ChatInput, FrequentQueries
├── components/Analysis/       AnalysisPage, StatisticsView
├── utils/nlToSql.js           백엔드 /chat/* 호출
└── data/mockData.js           추천 질문 목록
```

---

## 처리 흐름

```
질문 + 역할
   ↓
retriever      어느 테이블인가        (ontology_loader, fk_resolver 협업)
   ↓
term_resolver  모호어를 어느 컬럼으로 볼 것인가
   ↓
live_sample    실제 DB에 그 값이 있는가
   ↓
llm            SQL 생성 (실패 시 오류를 되먹여 재시도)
   ↓
sql_executor   SQL 실행 → 결과 반환
```

---

## 로컬 실행

Python 3.11 이상, Node.js, Ollama가 필요합니다.

```bash
ollama pull qwen2.5:7b
```

### 백엔드

```bash
cd backend
cp .env.example .env          # 최초 1회. MES_API_URL, MES_API_KEY 채우기
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/uvicorn app.main:app --port 8001 --reload
```

최초 실행 시 ChromaDB 임베딩 모델(약 90MB)을 내려받고 MES 스키마를 시딩합니다.

정상 기동:

```
[Startup] ChromaDB 초기화 중...
[ChromaDB] 기존 컬렉션 로드 완료 (491 문서)
[FKResolver] 그래프 구성 완료: 26 테이블, 26 FK 엣지
[OntologyEngine] 파싱 완료: 477 트리플
[Startup] 완료 — MES LLM API 준비됨
```

API 문서는 http://localhost:8001/docs 에서 확인합니다.

### 프론트

```bash
cd UI
npm install
npm run dev
```

`UI/.env` 의 `VITE_LLM_API_URL` 이 백엔드 주소를 가리켜야 합니다.
