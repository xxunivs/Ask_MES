"""
섹션 초안 MD 파일을 PAPER_FULL_DRAFT.md 에 병합 (유지보수용)

Usage: python eval/merge_paper_sections.py
"""
import re
from pathlib import Path

EVAL = Path(__file__).resolve().parent

HEADER = """# MES 도메인 온톨로지 기반 Hybrid RAG를 활용한 자연어→SQL 변환 연구

**NeuroFactory: Ontology-Guided Hybrid RAG for Manufacturing Execution System NL-to-SQL**

---

**저자** 정병화  
**소속** (소속 기관명)  
**실험 일자** 2026년 6월 3일  
**프로젝트** NeuroFactory / THiRA MES 3.1.0 / SKKU-LS Tirayutech RISE (S-2026-0945-000)

---

## 초록 (Abstract)

제조실행시스템(MES) 현장에서는 비전문 사용자도 LOT·작업지시·설비·공정 실적 등을 자연어로 조회하고자 하는 요구가 증가하고 있다. 그러나 MES 스키마는 `CIM_*` 테이블이 다수이고 한국어 도메인 용어·외래키 관계가 복잡하여, 범용 대규모언어모델(LLM)만으로는 정확한 SQL 생성이 어렵다. 본 논문은 **Ontology-Guided Hybrid RAG** 기반 NL→SQL 시스템 **NeuroFactory**를 제안한다. 한국어 개념어를 MES 테이블·컬럼에 매핑하는 OWL 온톨로지, ChromaDB 벡터 스키마 검색, FK 그래프 JOIN 경로 힌트를 결합하여 LLM(Qwen2.5:7b) 프롬프트 컨텍스트를 구성한다. 자체 구축 벤치마크 50문항에 대한 ablation 실험(2026-06-03, 스키마·코드값 검증 적용) 결과, 제안 구성(FULL)은 **VS 100%**, **EX_exec 60%**로 ablation 중 최고였다. B0~B3는 26~42% 수준이며, Hybrid RAG·사전 검증의 필요성을 확인하였다.

**핵심어:** 제조실행시스템, 자연어→SQL, 온톨로지, 검색증강생성(RAG), 대규모언어모델, THiRA MES

---

# 1. 서론

## 1.1 연구 배경

제조실행시스템(Manufacturing Execution System, MES)은 생산 로트 추적, 작업지시 관리, 설비·공정 실적 수집 등 제조 현장의 핵심 정보시스템이다. THiRA MES 3.1.0과 같이 `CIM_LOT`, `CIM_PRODUCTORDER`, `CIM_PROCESSSEGMENT` 등 다수의 운영 테이블을 가진 환경에서는, 현업 사용자가 SQL을 직접 작성하지 않고 **한국어 자연어**로 데이터를 조회하려는 요구가 커지고 있다.

최근 LLM을 활용한 Text-to-SQL(NL→SQL) 연구가 활발하나, 공개 벤치마크(WikiSQL, Spider 등) 중심의 연구가 많고, **도메인 특화 스키마·한국어 질의·운영 DB 제약**(예: `WITH (NOLOCK)`, 사이트 ID)이 강한 MES 환경에 대한 실증은 상대적으로 부족하다. 벡터 검색(RAG)만으로는 “홀드”, “TrackIn”, “자재 LOT” 등 MES 용어와 테이블 매핑이 불완전하고, 다중 테이블 JOIN 경로를 LLM이 스스로 추론하기 어렵다.

## 1.2 연구 목적 및 기여

본 연구의 목적은 (1) MES 도메인 온톨로지와 FK·RAG를 결합한 **Hybrid RAG** 기반 NL→SQL 아키텍처를 제안하고, (2) 자체 벤치마크와 ablation 실험으로 각 구성요소의 기여도를 정량 검증하는 것이다.

1. THiRA MES `CIM_*` 스키마와 한국어 개념어를 연결하는 **OWL 온톨로지** 및 개념 사전 구축  
2. 온톨로지·ChromaDB RAG·FK JOIN 힌트를 통합한 **NeuroFactory** 프로토타입  
3. 50문항 골드 벤치마크와 **VS·EX_exec·Table F1** 기반 실행 평가, B0~FULL ablation  
4. MES 현장 적용 가능성 실증(VS 100%, EX_exec 60%)

## 1.3 논문 구성

2장 관련 연구, 3장 제안 방법(그림 1), 4장 실험 및 결과(그림 2~5), 5장 논의, 6장 결론 순으로 기술한다.

---

# 2. 관련 연구

## 2.1 Text-to-SQL

Text-to-SQL은 자연어 질의를 관계형 DB 질의로 변환하는 문제이다. Spider, WikiSQL 등에서 높은 정확도가 보고되나, 스키마 규모·도메인 용어·DB 방언 등 운영 환경과의 괴리가 존재한다.

## 2.2 RAG와 스키마 링킹

RAG는 검색된 스키마 청크를 LLM에 주입한다. FK 관계 그래프와 JOIN 경로 추론(**스키마 링킹**) 연구도 있으며, 본 연구는 MES FK 그래프와 Dijkstra 최단 경로로 구현한다.

## 2.3 온톨로지

제조 영역 온톨로지 표준(ISO 18629, ISA-95 등)이 논의되었다. 본 연구는 THiRA MES 운영 테이블에 맞춘 **경량 OWL**과 JSON 개념 사전을 병행한다.

## 2.4 본 연구의 위치

MES 운영 DB **실행 기반 평가**와 **온톨로지·FK·RAG ablation**에 초점을 둔다.

---

# 3. 제안 방법

## 3.1 시스템 개요

**NeuroFactory**는 한국어 질의를 MS SQL `SELECT`로 변환하고 MES REST API로 실행한다.

| 단계 | 모듈 | 역할 |
|:----:|------|------|
| ① | OntologyEngine | 한국어 개념어 → `CIM_*` 테이블·컬럼 |
| ② | ChromaDB RAG | 스키마 청크 벡터 검색 (top-k=6) |
| ③ | FKPathResolver | Dijkstra JOIN 경로 힌트 |
| ④ | LLM | Qwen2.5:7b SQL 생성 → MES API |

**[그림 1] NeuroFactory NL→SQL 처리 파이프라인**

![그림 1](figures/fig1_system_architecture.png)

그림 1은 한국어 질의부터 MES DB 실행까지의 4단계 Hybrid RAG 파이프라인과 SQL 사후 검증 단계를 나타낸다.

## 3.2 MES 도메인 온톨로지

`mes_ontology.ttl`(OWL)과 `mes_concept_map.json`으로 홀드·불량·TrackIn·작업지시 등을 테이블에 매핑한다. `mapsToTable`, `skos:altLabel` 속성을 사용한다.

## 3.3 Hybrid RAG

`retrieve_context()`가 개념 매핑·벡터 검색·JOIN 힌트를 조합한다. `RetrievalConfig`로 B0~FULL ablation을 제어한다.

## 3.4 SQL 생성 규칙

`SELECT`만 허용, `WITH (NOLOCK)`, 날짜 미지정 시 기준일 1년 전, 불량률·TrackIn 집계 규칙을 프롬프트에 명시한다.

---

# 4. 실험 및 결과

"""


def clean_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    skip = False
    for line in lines:
        if line.startswith("> "):
            continue
        low = line.lower()
        if "체크리스트" in low or (low.startswith("## hwp") or low.startswith("# hwp")):
            skip = True
            continue
        if skip and line.startswith("---"):
            skip = False
            continue
        if skip:
            continue
        if line.startswith("# ") and "논문 초안용" in line:
            continue
        if line.startswith("## ") and any(
            k in line for k in ("절 맺음", "부록·각주", "4.1절과 연결")
        ):
            skip = True
            continue
        out.append(line)
    return out


def renumber_section(text: str, old_prefix: str, new_prefix: str) -> str:
    """4.2.3 -> 4.1.3 when old_prefix=4.2. and new_prefix=4.1."""
    pat = re.compile(rf"^(##?\s+){re.escape(old_prefix)}(\d+(?:\.\d+)*)", re.M)

    def repl(m):
        rest = m.group(2)
        return f"{m.group(1)}{new_prefix}{rest}"

    return pat.sub(repl, text)


def renumber_tables(text: str) -> str:
    reps = [
        ("**[표 A]", "**[표 1]"),
        ("**[표 B]", "**[표 2]"),
        ("**[표 C]", "**[표 3]"),
        ("**[표 1] Ablation별", "**[표 4] Ablation별"),
        ("**[표 2] 난이도별", "**[표 5] 난이도별"),
        ("**[표 3] 실행 실패", "**[표 6] 실행 실패"),
        ("표 1은", "표 4는"),
        ("표 1에", "표 4에"),
        ("4.3.4절", "4.5절"),
        ("4.3절", "4장"),
        ("4.4절", "5장"),
        ("5.1절", "5장"),
        ("4.5.1절", "4.5절"),
    ]
    for a, b in reps:
        text = text.replace(a, b)
    return text


def strip_leading_h1(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()


def main():
    s42 = clean_lines((EVAL / "PAPER_SECTION_4_2_DRAFT.md").read_text(encoding="utf-8").splitlines())
    s43 = clean_lines((EVAL / "PAPER_SECTION_4_3_DRAFT.md").read_text(encoding="utf-8").splitlines())
    s45_raw = (EVAL / "PAPER_SECTION_4_4_AND_5_DRAFT.md").read_text(encoding="utf-8")

    body42 = renumber_tables(
        renumber_section(strip_leading_h1("\n".join(s42)), "4.2.", "4.1.")
    )
    body42 = body42.replace("## 4.1 실험 환경 및 설계", "## 4.1 실험 환경 및 설계", 1)

    idx43 = 0
    for i, ln in enumerate(s43):
        if ln.startswith("## 4.3."):
            idx43 = i
            break
    body43 = renumber_tables(
        renumber_section(strip_leading_h1("\n".join(s43[idx43:])), "4.3.", "4.2.")
    )

    idx5 = s45_raw.find("# 4.4")
    body45 = s45_raw[idx5:]
    for stop in ["## hwp", "## 전체 논문"]:
        if stop in body45:
            body45 = body45.split(stop)[0]
    body45 = strip_leading_h1(body45)
    body45 = renumber_tables(body45)
    body45 = body45.replace("# 4.4 논의", "# 5. 논의")
    body45 = renumber_section(body45, "4.4.", "5.")
    idx_conc = body45.find("# 5. 결론")
    if idx_conc >= 0:
        disc = body45[:idx_conc].rstrip()
        conc = body45[idx_conc:].replace("# 5. 결론", "# 6. 결론")
        conc = renumber_section(conc, "5.", "6.")
        body45 = disc + "\n\n" + conc

    footer = """
---

# 참고문헌

1. Yu, T., et al. (2018). Spider. EMNLP.  
2. Karpukhin, V., et al. (2020). Dense Passage Retrieval. EMNLP.  
3. Lewis, P., et al. (2020). RAG for Knowledge-Intensive NLP. NeurIPS.  
4. THiRA MES 3.1.0 ERD 공정관리 (내부 문서).  

---

# 부록

- 실험 결과: `eval/results/experiment_20260603_182753/`  
- 벤치마크: `data/benchmark/mes_nl2sql_gold_v2.jsonl`  
- 그림 생성: `python eval/figures/generate_paper_figures.py`  
- 완성본 일괄: `python eval/build_paper_complete.py`  
- Word 생성: `python eval/make_paper_full_docx.py`

---

*통합본 v2 — `python eval/merge_paper_sections.py` 로 재생성*
"""

    full = HEADER + body42 + "\n\n" + body43 + "\n\n" + body45.strip() + footer
    out = EVAL / "PAPER_FULL_DRAFT.md"
    out.write_text(full, encoding="utf-8")
    print(f"완료: {out} ({len(full)} chars)")


if __name__ == "__main__":
    main()
