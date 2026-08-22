# 논문 실험 진행 가이드 (NeuroFactory)

`논문초안_11조_정병화.hwp` 실험 절을 채우기 위한 **권장 순서**입니다.

## 사전 준비

1. **Ollama** 실행 + `qwen2.5:7b` 모델
2. **`.env`** — `MES_API_URL`, `MES_API_KEY` 유효
3. `mes-llm-api` 루트에서 venv 활성화
4. **날짜 기준** — 개발 DB 벤치마크는 `MES_DATE_MODE=dev_last_year`(기본). 최근 dev 데이터는 운영 흐름이 아니어서 **1년 전 구간**을 실데이터로 사용. 운영 DB 연결 시 `.env`에 `MES_DATE_MODE=production` 설정.

```powershell
cd D:\YG-1고도화 소스\NeuroFactory\mes-llm-api
.\venv\Scripts\activate
```

---

## Step 1 — 골드 SQL 검증 (필수)

DB에서 50문항 골드 SQL이 모두 실행되는지 확인합니다.

```powershell
python eval\validate_gold.py
```

- 실패 문항 ID가 출력되면 `mes_nl2sql_gold_v2.jsonl`의 `gold_sql`·`STATE` 코드 수정
- 리포트: `eval/results/gold_validation_*.json`

**논문에 기록**: 골드 검증 일자, 통과율, 실패 문항 처리 방법

---

## Step 1b — 코드값 DISTINCT 수집 (권장, 배포 전·주기)

`ISHOLD='Y'` 등 WHERE 절 리터럴을 운영 DB에서 자동 수집합니다.

```powershell
python scripts\collect_code_values.py
```

- 입력: `data/mes_code_profile.json` (수집 대상 컬럼)
- 출력: `data/mes_code_values.json` (허용 값 + LLM 금지 리터럴)
- 반영: 프롬프트·`sql_validator`·ChromaDB 시딩 (`mes_code_values.json` 변경 시 `chroma_db` 재시딩)

API 없이 시드만 쓸 경우: `mes_code_values.json`의 `CIM_LOT.ISHOLD` → `Y`,`N` 유지.

---

## Step 2 — Ablation 5조건 실험 (핵심)

| Preset | 구성 |
|--------|------|
| B0 | 스키마 요약만 |
| B1 | + ChromaDB RAG |
| B2 | + FK JOIN 힌트 |
| B3 | + 온톨로지 개념 매핑 |
| FULL | B2 + B3 (전체) |

```powershell
# 약 50문항 × 5조건 → Ollama 시간 소요 (수 시간 가능)
python eval\run_all_ablations.py --execute
```

출력 폴더 예: `eval/results/experiment_20260602_143000/`

- `paper_table.md` — 논문 표에 붙여넣기
- `ablation_summary.csv` — Excel/그래프용
- `run_B1_*.csv` … 개별 상세 결과

**논문 표 예시** (`paper_table.md` 내용 그대로 사용)

---

## Step 3 — 난이도·JOIN별 분석

```powershell
python eval\score.py eval\results\experiment_YYYYMMDD_HHMMSS\run_FULL_*.csv --by difficulty
python eval\score.py eval\results\experiment_YYYYMMDD_HHMMSS\run_FULL_*.csv --by requires_join
```

논문 4.3절: easy/medium/hard, JOIN 유무별 EX_exec 비교 1~2문단

---

## Step 4 — 실패 사례 정성 분석 (5~10건)

`run_FULL_*.csv`에서 `exec_ok=False` 또는 `valid_sql=False` 행 추출:

- 잘못된 테이블/컬럼
- 날짜 규칙(1년 전 기준) 미준수
- JOIN 누락

논문 4.4절: 한계 및 개선 방향

---

## Step 5 — 논문 초안 반영 체크리스트

| 절 | 채울 내용 | 산출물 |
|----|-----------|--------|
| 3.1 시스템 | 4단계 파이프라인 | `make_arch_doc.py` → docx |
| 3.2 온톨로지 | OWL + 개념 매핑 | `data/mes_ontology.ttl` |
| 4.1 데이터셋 | 50문항, 난이도 분포 | `DATASET_INDEX.md` |
| **4.2 실험 환경** | **hwp 초안** | **`eval/PAPER_SECTION_4_2_DRAFT.md`** |
| 4.3 결과 | VS, EX_exec, Table F1 | `eval/PAPER_SECTION_4_3_DRAFT.md`, `paper_table.md` |
| **4.4 논의** | **hwp 초안** | **`eval/PAPER_SECTION_4_4_AND_5_DRAFT.md`** |
| **5 결론** | **hwp 초안** | **동일 파일 5장** |

---

## 빠른 스모크 테스트 (5문항)

```powershell
python eval\run_benchmark.py --preset FULL --execute --ids Q001,Q002,Q003,Q004,Q005
python eval\score.py eval\results\latest.csv
```

---

## 다음 확장 (v3)

- [ ] 80~100문항 (`docs/db/procedures` 기반)
- [ ] EX 결과 동등성(행 집합 비교) 강화
- [ ] 논문용 막대 그래프 스크립트 (`eval/plot_results.py`)
