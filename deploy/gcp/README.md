# Google Cloud 배포 메모

마지막 확인: 2026-08-22

## 1. 현재 동작 구조

```text
사용자 브라우저
-> 프론트 (Cloud Run)
-> FastAPI 백엔드 (api.neurofactory.cloud)
-> LLM (Ollama, qwen2.5-coder:32b)
-> MES DB API (<사내 MES DB>)
```

## 2. 현재 배포 주소

```text
프론트:  https://neurofactory-frontend-<project-number>.us-central1.run.app   (동작 확인)
백엔드:  https://api.neurofactory.cloud                                    (동작 확인)
```

`GET /chat/health` 응답으로 LLM·DB 연결 상태를 확인할 수 있다.

```json
{"ollama":"ok","model":"qwen2.5-coder:32b","db":"ok","db_server":"<사내 MES DB>"}
```

프론트는 빌드 시점에 `VITE_LLM_API_URL`이 고정되므로 백엔드 주소가 바뀌면 재빌드가 필요하다.

## 3. 중단된 구성

아래는 과거에 쓰다가 현재는 꺼져 있다. 되살리려면 주소부터 새로 확보해야 한다.

- GPU VM 위의 vLLM 서버 (`<GPU VM>:8008`, 이전에는 `<GPU VM>:8008`) — 응답 없음
- 이전 백엔드 Cloud Run 주소 (`neurofactory-backend-<project-number>.us-central1.run.app`) — 응답 없음
- 팀원 PC 에서 Cloudflare 터널로 띄우던 `mes-api:8000` — 폐지됨.
  현재 SQL 실행은 백엔드 자신의 `POST /chat/sql-execute` 가 담당한다.

`vllm/Dockerfile` 은 vLLM 서버로 되돌릴 때를 위해 남겨 둔 것이고, 현재 배포에는 쓰이지 않는다.

## 4. 환경변수

백엔드 (`backend/.env`):

```env
LLM_PROVIDER=ollama          # vllm 로 바꾸면 VLLM_API_URL 을 사용
LLM_MODEL=<모델명>
OLLAMA_URL=<ollama 주소>
MES_API_URL=https://api.neurofactory.cloud
MES_API_KEY=<mes-api-key>
CHROMA_PATH=./vector_index
RAG_TOP_K=6
```

프론트 (`UI/.env`):

```env
VITE_LLM_API_URL=https://api.neurofactory.cloud
```

## 5. 배포 순서

1. Google Cloud 프로젝트 생성
2. Billing 예산 알림 설정
3. LLM 준비 — Ollama 호스트를 띄우고 `OLLAMA_URL` 확보
   (vLLM 으로 갈 경우: GPU quota 확인 → `vllm/Dockerfile` 로 서버 실행 → `GET /v1/models` 확인)
4. 백엔드 Cloud Run 배포 — **`backend/` 디렉터리에서 빌드한다.** `Dockerfile` 과 `.dockerignore` 가 그 안에 있고, 실행 대상은 `app.main:app` 이다.
5. `GET /chat/health` 로 LLM·DB 연결 확인
6. 프론트 배포 (`UI/`, `cloudbuild.yaml` 의 `_VITE_LLM_API_URL` 에 백엔드 주소 전달)
7. 웹에서 질문 테스트

## 6. 테스트 질문

- `홀드 상태인 LOT 목록 보여줘`
- `LOT ID와 제품명을 함께 보여줘`
- `지난달 설비 가동 추이 알려줘`
