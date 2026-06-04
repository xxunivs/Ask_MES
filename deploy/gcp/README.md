# Google Cloud 배포 메모

목표 구조:

```text
사용자 브라우저
-> 프론트 서버
-> FastAPI 백엔드
-> GPU vLLM 서버(Qwen3.5-9B)
-> MES DB API
```

## 1. 권장 1차 구조

- 프론트: Cloud Run 또는 Vercel
- 백엔드: Cloud Run
- AI 서버: Google Compute Engine GPU VM 또는 Cloud Run GPU

처음에는 GPU VM이 디버깅이 쉽다. 테스트할 때만 켜고, 끝나면 중지한다.

## 2. 필요한 환경변수

백엔드:

```env
LLM_PROVIDER=vllm
LLM_MODEL=qwen35-9b
VLLM_API_URL=https://<vllm-server-url>/v1
VLLM_API_KEY=EMPTY
MES_API_URL=https://<mes-api-url>
MES_API_KEY=<mes-api-key>
CHROMA_PATH=./chroma_db
RAG_TOP_K=6
```

프론트:

```env
VITE_LLM_API_URL=https://<backend-url>
```

## 2-1. 현재 배포 주소

```text
프론트:  https://neurofactory-frontend-<project-number>.us-central1.run.app
백엔드:  https://neurofactory-backend-<project-number>.us-central1.run.app
AI 서버: http://<GPU VM>:8008/v1
```

현재 백엔드는 Cloud Run, AI 서버는 GCP GPU VM에서 동작한다.
프론트는 빌드 시점에 `VITE_LLM_API_URL`이 고정되므로 백엔드 주소가 바뀌면 재빌드가 필요하다.

## 3. 배포 순서

1. Google Cloud 프로젝트 생성
2. Billing 예산 알림 설정
3. GPU quota 확인 또는 요청
4. GPU VM 또는 Cloud Run GPU로 vLLM 실행
5. `GET /v1/models`로 `qwen35-9b` 확인
6. 백엔드 Cloud Run 배포
7. `GET /chat/health`로 LLM 연결 확인
8. 프론트 배포
9. 웹에서 역할 선택 후 질문 테스트

## 4. 테스트 질문

- 품질팀: `이번 달 불량 보여줘`
- 생산팀: `이번 달 불량 보여줘`
- 관리팀: `이번 달 불량 보여줘`
- 생산팀: `완료된 작업지시 실적 보여줘`
- 설비팀: `지난달 설비 가동 추이 알려줘`

역할에 따라 같은 표현이 다른 SQL 의미로 해석되는지 확인한다.
