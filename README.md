# NeuroFactory

자연어 질문을 SQL로 바꿔 MES(제조실행시스템) DB를 조회하는 시스템입니다.
같은 표현이라도 질문자의 역할(품질팀/생산팀/설비팀/관리팀)에 따라 다른 의미로 해석합니다.

FastAPI + ChromaDB + OWL 온톨로지 + Ollama

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
├── main.py                    FastAPI 진입점 (기동 시 ChromaDB 시딩)
├── requirements.txt
├── Dockerfile                 ← 배포 시 이 폴더에서 빌드
├── .env                       환경 설정 (git 제외)
├── .env.example
├── convert_ontology.py        온톨로지 JSON → data/mes_schema.json 변환 도구
│
├── data/
│   ├── mes_schema.json        MES 테이블·컬럼·FK 정의. 모든 모듈의 기준 파일
│   │                          ※ 바뀌면 서버 재시작 시 자동 재시딩
│   ├── mes_ontology.ttl       개념어 ↔ 테이블 매핑, JOIN 조건 (OWL/Turtle)
│   └── mes_concept_map.json   온톨로지 로딩 실패 시 쓰는 폴백 매핑
│
├── core/
│   ├── config.py              .env 값 로딩
│   ├── ollama.py              LLM 호출 (Ollama / vLLM 전환)
│   ├── db_client.py           SQL 실행 위임 클라이언트
│   ├── retriever.py           ChromaDB 검색 — 질문에 맞는 테이블 선별
│   ├── ontology_loader.py     온톨로지 기반 개념어 인식, JOIN 힌트 추출
│   ├── fk_resolver.py         FK 그래프 + Dijkstra 최단 JOIN 경로 계산
│   ├── db_context.py          실 DB 샘플 조회로 컨텍스트 보강, SQL 검증
│   └── term_resolver.py       모호어 해석 — 역할·맥락 기반 컬럼 선택
│
├── routers/
│   └── chat.py                API 엔드포인트, 프롬프트, SQL 재시도 루프
│
└── chroma_db/                 벡터 DB (자동 생성, 삭제해도 재시딩됨)
```

### 처리 흐름

```
질문 + 역할
   ↓
retriever      어느 테이블인가        (ontology_loader, fk_resolver 협업)
   ↓
term_resolver  모호어를 어느 컬럼으로 볼 것인가
   ↓
db_context     실제 DB에 그 값이 있는가
   ↓
ollama         SQL 생성 (실패 시 오류를 되먹여 재시도)
   ↓
db_client      SQL 실행 → 결과 반환
```

---

## 사전 요구사항

- Python 3.11 이상
- Node.js (UI 실행 시)
- Ollama — https://ollama.com/download
  ```bash
  ollama pull qwen2.5:7b
  ```

---

## 로컬 실행

### 백엔드

```bash
cd backend
cp .env.example .env          # 최초 1회. MES_API_URL, MES_API_KEY 채우기
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/uvicorn main:app --port 8001 --reload
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

### 프론트

```bash
cd UI
npm install
npm run dev
```

`UI/.env` 의 `VITE_LLM_API_URL` 이 백엔드 주소를 가리켜야 합니다.

---

## 접속 주소

| 용도 | URL |
|---|---|
| Swagger UI | http://localhost:8001/docs |
| 서버 상태 | http://localhost:8001/health |
| LLM·DB 연결 확인 | http://localhost:8001/chat/health |

배포본은 `deploy/gcp/README.md` 참고.

---

## API

### 자연어 → SQL 조회

`POST /chat/nl-to-sql`

```json
{
  "question": "이번 달 불량 보여줘",
  "limit": 100,
  "user_role": "quality",
  "current_view": "chat",
  "conversation_context": []
}
```

`user_role`: `quality` | `production` | `equipment` | `management` | `general`

```json
{
  "success": true,
  "sql": "SELECT TOP 20 SUM(ISNULL(L.[DEFECTQTY], 0)) AS [값] FROM CIM_LOTDEFECT L WITH (NOLOCK) WHERE ...",
  "description": "\"이번 달 불량 보여줘\" 질문에서 불량 해석을 고정한 검증 SQL입니다.",
  "data": { "columns": ["값"], "rows": [{ "값": 160.0 }], "count": 1 },
  "db_error": null,
  "term_note": "...",
  "term_resolution": {
    "resolved_terms": [
      {
        "term": "불량",
        "selected_meaning": "CIM_LOTDEFECT.DEFECTQTY 기준 수량",
        "selected_columns": ["CIM_LOTDEFECT.DEFECTQTY"],
        "confidence": 0.55
      }
    ]
  }
}
```

`term_resolution` 은 모호어를 어떤 근거로 어느 컬럼에 대응시켰는지 담습니다.

### 데이터 분석

`POST /chat/analyze`

```json
{
  "question": "불량률이 높은 원인이 뭔지 분석해줘",
  "data": { "columns": ["LOTID", "LOSSQTY"], "rows": [] }
}
```

---

## 테스트 질문

역할에 따라 해석이 갈리는지 확인하는 질문:

```
품질팀 / 생산팀 / 관리팀 : 이번 달 불량 보여줘
생산팀 : 완료된 작업지시 실적 보여줘
설비팀 : 지난달 설비 가동 추이 알려줘
```

일반 조회:

```
홀드 상태인 LOT 목록 보여줘
설비 유형별 설비 수를 보여줘
완료 상태가 아닌 작업지시 목록 보여줘
자재 LOT 중 현재 수량이 0인 것 보여줘
공정 세그먼트 전체 목록과 소요시간을 보여줘
```

---

## 자주 발생하는 오류

| 오류 | 원인 | 해결 |
|---|---|---|
| `Ollama 연결 실패` | Ollama 미실행 | Ollama 앱 실행 후 `ollama list` 확인 |
| `401 Unauthorized` | MES API 키·주소 오류 | `.env` 의 `MES_API_URL`, `MES_API_KEY` 확인 |
| `500 Internal Server Error` | 생성된 SQL이 없는 컬럼 참조 | 질문을 더 구체적으로 바꿔 재시도 |
| `Ollama 타임아웃` | 모델 처리 과부하 | 잠시 후 재시도 |

---

## 스키마 갱신

MES 테이블·컬럼이 바뀐 경우, 온톨로지 JSON을 갱신한 뒤 변환합니다.

```bash
cd backend
./venv/bin/python convert_ontology.py mes_ontology_fk.json data/mes_schema.json
```

`data/mes_schema.json` 이 바뀌면 서버 재시작 시 ChromaDB가 자동으로 재시딩합니다.
