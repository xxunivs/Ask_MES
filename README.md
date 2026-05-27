# MES LLM API — 설치 및 사용 가이드

자연어 질문을 SQL로 변환하여 MES DB를 조회하는 API 서버입니다.  
(LangChain + ChromaDB + Ollama + FastAPI)

---

## 아키텍처

```
사용자 질문 (자연어)
       ↓
MES LLM API (port 8001)
  ├─ ChromaDB RAG  → 관련 스키마 검색
  ├─ Ollama LLM    → SQL 생성
  └─ MES API       → SQL 실행 → 결과 반환
```

---

## 사전 설치 요구사항

### 1. Python 3.11 이상
- 다운로드: https://www.python.org/downloads/
- 설치 시 **"Add Python to PATH"** 반드시 체크
- 설치 확인:
  ```powershell
  python --version
  # Python 3.11.x 이상이어야 함
  ```

### 2. Ollama (로컬 LLM 엔진)
- 다운로드: https://ollama.com/download
- 설치 후 모델 다운로드 (약 4.7GB):
  ```powershell
  ollama pull qwen2.5:7b
  ```
- 설치 확인:
  ```powershell
  ollama list
  # qwen2.5:7b 가 목록에 있어야 함
  ```

---

## 설치 방법

### 1. 프로젝트 폴더 복사
팀 공유 드라이브에서 `mes-llm-api` 폴더를 로컬에 복사합니다.

### 2. 환경 설정 파일 수정
`mes-llm-api\.env` 파일을 메모장으로 열어 아래 항목을 확인/수정합니다.

```env
# Ollama 설정 (기본값 유지)
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b

# MES DB API 접속 정보 (담당자에게 문의)
MES_API_URL=https://xxxx.trycloudflare.com   ← 현재 터널 URL 확인 필요
MES_API_KEY=<MES_API_KEY>                          ← API 키

# 아래는 수정 불필요
CHROMA_PATH=./chroma_db
RAG_TOP_K=6
```

> **MES_API_URL 주의**: Cloudflare 터널 URL은 서버 재시작 시 변경될 수 있습니다.  
> 변경된 경우 담당자에게 최신 URL을 받아서 수정하세요.

### 3. 서버 실행
```powershell
.\start.bat
```

**최초 실행 시** 아래 작업이 자동으로 진행됩니다 (시간 소요):
- Python 가상환경 생성 (`venv/` 폴더)
- 패키지 자동 설치
- ChromaDB 임베딩 모델 다운로드 (약 90MB, 1회만)
- MES 스키마 시딩

**정상 실행 화면:**
```
[Startup] ChromaDB 초기화 중...
[ChromaDB] 기존 컬렉션 로드 완료 (XXX 문서)
[Startup] 완료 — MES LLM API 준비됨
INFO: Uvicorn running on http://0.0.0.0:8001
```

---

## 접속 주소

| 용도 | URL |
|---|---|
| Swagger UI (API 테스트) | http://localhost:8001/docs |
| 서버 상태 확인 | http://localhost:8001/health |
| Ollama 연결 확인 | http://localhost:8001/chat/health |

---

## API 사용법

### 자연어 → SQL 조회
`POST /chat/nl-to-sql`

**요청:**
```json
{
  "question": "홀드 상태인 LOT 목록 보여줘",
  "limit": 100
}
```

**응답:**
```json
{
  "success": true,
  "sql": "SELECT TOP 100 * FROM CIM_LOT WITH (NOLOCK) WHERE ISHOLD = 'Y'",
  "description": "홀드 상태인 LOT 목록 조회",
  "data": {
    "columns": ["LOTID", "SITEID", ...],
    "rows": [...],
    "count": 5
  },
  "db_error": null
}
```

### 데이터 분석
`POST /chat/analyze`

**요청:**
```json
{
  "question": "불량률이 높은 원인이 뭔지 분석해줘",
  "data": {
    "columns": ["LOTID", "LOSSQTY", "ORIGINALQTY"],
    "rows": [...]
  }
}
```

---

## 테스트 질문 예시

```
LOT 목록 100건 보여줘
홀드 상태인 LOT 목록 보여줘
설비 전체 목록 보여줘
설비 유형별 설비 수를 보여줘
작업지시 전체 목록과 상태를 보여줘
완료 상태가 아닌 작업지시 목록 보여줘
자재 LOT 중 현재 수량이 0인 것 보여줘
안전재고가 있는 자재 목록 보여줘
공정 세그먼트 전체 목록과 소요시간을 보여줘
불량 유형 목록 보여줘
```

---

## 주요 파일 설명

```
mes-llm-api/
├── start.bat                  ← 서버 실행 스크립트 (더블클릭 또는 PowerShell에서 .\start.bat)
├── .env                       ← 환경 설정 (MES_API_URL, MES_API_KEY 수정 필요)
├── main.py                    ← FastAPI 앱 진입점
├── requirements.txt           ← Python 패키지 목록
├── convert_schema.py          ← DB 스키마 갱신 도구 (관리자용)
│
├── data/
│   └── mes_schema.json        ← MES 테이블/컬럼 정의 (RAG 학습 데이터)
│                                 ※ 이 파일이 바뀌면 서버 재시작 시 자동 재시딩
│
├── core/
│   ├── config.py              ← .env 값 로딩
│   ├── ollama.py              ← Ollama LLM 호출 클라이언트
│   ├── db_client.py           ← MES DB API 호출 클라이언트
│   └── retriever.py           ← ChromaDB RAG 검색 엔진
│
├── routers/
│   └── chat.py                ← API 엔드포인트 + LLM 프롬프트 정의
│
├── chroma_db/                 ← ChromaDB 벡터 DB (자동 생성, 삭제 시 재시딩)
└── venv/                      ← Python 가상환경 (자동 생성, 공유 불필요)
```

---

## 자주 발생하는 오류

| 오류 | 원인 | 해결 |
|---|---|---|
| `Ollama 연결 실패` | Ollama가 실행되지 않음 | 작업표시줄에서 Ollama 확인, 없으면 Ollama 앱 실행 |
| `401 Unauthorized` | MES API 키 오류 또는 URL 만료 | `.env`의 `MES_API_URL`, `MES_API_KEY` 담당자 확인 |
| `500 Internal Server Error` | 생성된 SQL에 없는 컬럼 사용 | 질문을 더 구체적으로 바꿔서 재시도 |
| `Ollama 타임아웃` | 모델 처리 과부하 | 잠시 후 재시도 |
| `start.bat` 실행 안됨 | PowerShell 실행 정책 | `.\start.bat` 으로 실행 |

---

## 스키마 갱신 방법 (관리자용)

DB 테이블/컬럼이 변경된 경우:

1. MSSQL에서 쿼리 실행 후 결과를 `raw_schema.json`으로 저장:
```sql
SELECT t.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE,
       c.CHARACTER_MAXIMUM_LENGTH, c.IS_NULLABLE,
       CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 'YES' ELSE 'NO' END AS IS_PK
FROM INFORMATION_SCHEMA.TABLES t
JOIN INFORMATION_SCHEMA.COLUMNS c ON t.TABLE_NAME = c.TABLE_NAME
LEFT JOIN (
    SELECT ku.TABLE_NAME, ku.COLUMN_NAME
    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
    WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
) pk ON c.TABLE_NAME = pk.TABLE_NAME AND c.COLUMN_NAME = pk.COLUMN_NAME
WHERE t.TABLE_TYPE = 'BASE TABLE' AND t.TABLE_NAME LIKE 'CIM_%'
ORDER BY t.TABLE_NAME, c.ORDINAL_POSITION
FOR JSON PATH
```

2. 변환 스크립트 실행:
```powershell
.\venv\Scripts\python convert_schema.py
```

3. 서버 재시작 (자동으로 재시딩):
```powershell
.\start.bat
```
