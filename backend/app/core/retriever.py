"""
app/core/retriever.py  (v2 — Ontology-Guided Hybrid RAG)
=====================================================
v1 대비 변경사항:
  1. FKPathResolver 통합 → ChromaDB가 찾은 테이블 간 JOIN 경로 자동 계산
  2. ConceptMapper 통합 → 한국어 개념어 → 관련 테이블/컬럼 보강 검색
  3. retrieve_context() 반환값에 "## JOIN 힌트" 섹션 추가
  4. 싱글턴 초기화 순서: init_chroma() → FKResolver / ConceptMapper 동시 초기화

아키텍처:
  NL Query
    ↓
  [ConceptMapper] 개념어 인식 → 추가 테이블 후보 확보
    ↓
  [ChromaDB] 벡터 유사도 검색 → 관련 컬럼/테이블 top-k
    ↓
  [FKPathResolver] 식별된 테이블 간 Dijkstra 최단 JOIN 경로 계산
    ↓
  Prompt Context (스키마 청크 + JOIN 힌트 + 개념 매핑)
    ↓
  Ollama Qwen2.5:7b → SQL 생성
"""

import hashlib
import json
import os
from typing import Optional

from dataclasses import dataclass

import chromadb
from chromadb.utils import embedding_functions

from app.core.config import CHROMA_PATH, RAG_TOP_K, EMBED_MODEL, EMBED_BACKEND, OLLAMA_URL
from app.core.fk_resolver import FKPathResolver, get_resolver
from app.core.ontology_loader import get_concept_engine

# ──────────────────────────────────────────────────────────────────
# 임베딩 함수
# ──────────────────────────────────────────────────────────────────


class OllamaEmbeddingFunction(embedding_functions.EmbeddingFunction):
    """Ollama /api/embeddings 를 부르는 Chroma 임베딩 함수.

    논문 구성이 bge-m3 이고, 4월 프로토타입도 OllamaEmbeddings(model="bge-m3")
    를 썼다. Chroma 기본 임베딩(all-MiniLM-L6-v2)은 영어 전용이라 한국어
    질의에서 검색 품질이 무너진다.
    """

    def __init__(self, model: str, base_url: str):
        self._model = model
        self._base_url = base_url.rstrip("/")

    def name(self) -> str:
        return f"ollama-{self._model}"

    def __call__(self, input):
        import httpx

        vectors = []
        with httpx.Client(timeout=120.0) as client:
            for text in input:
                resp = client.post(
                    f"{self._base_url}/api/embeddings",
                    json={"model": self._model, "prompt": text},
                )
                resp.raise_for_status()
                vectors.append(resp.json()["embedding"])
        return vectors


def _embedding_function():
    if EMBED_BACKEND == "ollama":
        return OllamaEmbeddingFunction(EMBED_MODEL, OLLAMA_URL)
    return embedding_functions.DefaultEmbeddingFunction()


# ──────────────────────────────────────────────────────────────────
# 경로 설정
# ──────────────────────────────────────────────────────────────────

_BASE_DIR       = os.path.dirname(__file__)
SCHEMA_PATH     = os.path.join(_BASE_DIR, "../../data/mes_schema.json")
COLLECTION_NAME = "mes_schema"
HASH_FILE       = os.path.join(CHROMA_PATH, ".schema_hash")

# ──────────────────────────────────────────────────────────────────
# 전역 싱글턴
# ──────────────────────────────────────────────────────────────────

_collection:     Optional[chromadb.Collection] = None
_fk_resolver:    Optional[FKPathResolver]       = None
_concept_engine = None


@dataclass(frozen=True)
class RetrievalConfig:
    """벤치마크 ablation용 RAG 구성."""
    use_rag: bool = True
    use_ontology: bool = True
    use_fk: bool = True

    @classmethod
    def from_preset(cls, name: str) -> "RetrievalConfig":
        presets = {
            "B0": cls(use_rag=False, use_ontology=False, use_fk=False),
            "B1": cls(use_rag=True, use_ontology=False, use_fk=False),
            "B2": cls(use_rag=True, use_ontology=False, use_fk=True),
            "B3": cls(use_rag=True, use_ontology=True, use_fk=False),
            "FULL": cls(use_rag=True, use_ontology=True, use_fk=True),
        }
        key = name.upper()
        if key not in presets:
            raise ValueError(f"Unknown preset: {name}. Use one of {list(presets)}")
        return presets[key]


# ──────────────────────────────────────────────────────────────────
# ChromaDB 초기화 및 시딩
# ──────────────────────────────────────────────────────────────────

def _schema_hash() -> str:
    with open(SCHEMA_PATH, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def _saved_hash() -> str:
    if os.path.exists(HASH_FILE):
        return open(HASH_FILE).read().strip()
    return ""


def _save_hash(h: str):
    os.makedirs(CHROMA_PATH, exist_ok=True)
    with open(HASH_FILE, "w") as f:
        f.write(h)


def init_chroma():
    """
    앱 시작 시 1회 호출.
    ChromaDB + FKPathResolver + ConceptMapper 동시 초기화.
    """
    global _collection, _fk_resolver, _concept_engine

    # ── ChromaDB ──
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    ef = _embedding_function()
    current_hash = _schema_hash()

    if current_hash != _saved_hash():
        print("[ChromaDB] 스키마 변경 감지 → 컬렉션 재생성 중...")
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        # 논문 구성은 코사인 유사도. Chroma 기본은 L2 라서 명시해야 한다.
        _collection = client.create_collection(
            name=COLLECTION_NAME,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
        _seed_schema()
        _save_hash(current_hash)
    else:
        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
        if _collection.count() == 0:
            print("[ChromaDB] 컬렉션 비어 있음 → 시딩 시작...")
            _seed_schema()
            _save_hash(current_hash)
        else:
            print(f"[ChromaDB] 기존 컬렉션 로드 완료 ({_collection.count()} 문서)")

    # ── FKPathResolver ──
    _fk_resolver = get_resolver(SCHEMA_PATH)

    # ── ConceptEngine (OWL 또는 JSON 폴백) ──
    _concept_engine = get_concept_engine()

    print("[Retriever] Ontology-Guided Hybrid RAG 초기화 완료")


def _seed_schema():
    """mes_schema.json을 읽어 테이블/컬럼 단위 문서로 ChromaDB에 삽입"""
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)

    docs, ids, metas = [], [], []

    for table in schema["tables"]:
        tname = table["name"]
        tdesc = table.get("description", "")
        cols_summary = ", ".join(
            f"{c['name']}({c.get('type', '')})" for c in table.get("columns", [])
        )
        fk_info = ""
        if table.get("foreign_keys"):
            fk_lines = [
                f"{fk['column']} → {fk['ref_table']}.{fk['ref_column']}"
                for fk in table["foreign_keys"]
            ]
            fk_info = "\nFK: " + ", ".join(fk_lines)

        table_doc = (
            f"[테이블] {tname}\n"
            f"설명: {tdesc}\n"
            f"컬럼: {cols_summary}"
            f"{fk_info}"
        )
        docs.append(table_doc)
        ids.append(f"tbl_{tname}")
        metas.append({"type": "table", "table": tname})

        for col in table.get("columns", []):
            cname = col["name"]
            cdesc = col.get("description", "")
            ctype = col.get("type", "")
            col_doc = (
                f"[컬럼] {tname}.{cname} ({ctype})\n"
                f"설명: {cdesc}"
            )
            docs.append(col_doc)
            ids.append(f"col_{tname}_{cname}")
            metas.append({"type": "column", "table": tname, "column": cname})

    batch_size = 500
    for i in range(0, len(docs), batch_size):
        _collection.add(
            documents=docs[i: i + batch_size],
            ids=ids[i: i + batch_size],
            metadatas=metas[i: i + batch_size],
        )

    print(f"[ChromaDB] 시딩 완료: {len(docs)} 문서 ({len(schema['tables'])} 테이블)")


# ──────────────────────────────────────────────────────────────────
# 핵심 함수: Ontology-Guided Hybrid RAG 컨텍스트 생성
# ──────────────────────────────────────────────────────────────────

def minimal_schema_context(max_tables: int = 40) -> str:
    """B0 베이스라인: 테이블·PK 목록만 제공."""
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    lines = ["[MES 스키마 요약 — 테이블 목록만]"]
    for table in schema["tables"][:max_tables]:
        tname = table["name"]
        pk = ", ".join(table.get("pk") or [])
        lines.append(f"- {tname}" + (f" (PK: {pk})" if pk else ""))
    return "\n".join(lines)


def retrieve_context(
    query: str,
    n: int = None,
    config: Optional[RetrievalConfig] = None,
) -> str:
    """
    자연어 쿼리에 대한 하이브리드 RAG 컨텍스트 반환.

    3단계 파이프라인:
      1. ConceptMapper  → 개념어 기반 테이블/컬럼 후보 식별
      2. ChromaDB       → 벡터 유사도 top-k 검색
      3. FKPathResolver → 식별된 테이블 간 JOIN 경로 계산

    config: RetrievalConfig — ablation 시 B0~FULL 프리셋 사용.
            생략하면 세 단계를 모두 사용한다(기존 동작).

    Returns:
      프롬프트에 주입할 컨텍스트 문자열
    """
    cfg = config or RetrievalConfig()

    if not cfg.use_rag and not cfg.use_ontology and not cfg.use_fk:
        return minimal_schema_context()

    if _collection is None:
        init_chroma()

    k = n or RAG_TOP_K

    # ── Step 1: 개념어 기반 테이블 식별 (OntologyEngine / JSON 폴백) ──
    concept_tables: list[str] = []
    concept_hint:   str       = ""
    if cfg.use_ontology and _concept_engine:
        concept_tables = _concept_engine.find_tables(query)
        concept_hint   = _concept_engine.get_concept_hint(query)

    # ── Step 2: ChromaDB 벡터 검색 ──
    chroma_docs: list[str] = []
    chroma_tables: list[str] = []
    if cfg.use_rag:
        results  = _collection.query(query_texts=[query], n_results=k)
        chroma_docs   = results["documents"][0]
        chroma_metas  = results["metadatas"][0]

        # 검색된 테이블 목록 추출 (순서 유지 dedup)
        for m in chroma_metas:
            t = m.get("table", "")
            if t and t not in chroma_tables:
                chroma_tables.append(t)

    # ConceptMapper + ChromaDB 결과 병합 (중복 제거, 개념 테이블 우선)
    all_tables: list[str] = list(concept_tables)
    for t in chroma_tables:
        if t not in all_tables:
            all_tables.append(t)

    # ── Step 3: Dijkstra FK-path JOIN 힌트 ──
    join_hint = ""
    if cfg.use_fk and _fk_resolver and len(all_tables) >= 2:
        join_sql = _fk_resolver.get_join_sql(all_tables[:5], max_hops=4)
        if join_sql:
            join_hint = f"\n\n## JOIN 경로 힌트 (Dijkstra 최단경로)\n{join_sql}"
            # 경유 테이블을 컨텍스트에 추가 (스키마 청크 보강)
            _augment_intermediate_tables(join_sql, all_tables)

    # ── 컨텍스트 조립 ──
    sections: list[str] = []
    if chroma_docs:
        sections.append("\n---\n".join(chroma_docs))
    elif concept_tables and cfg.use_ontology:
        sections.append(
            "[ChromaDB 미사용] 온톨로지로 식별된 테이블: "
            + ", ".join(concept_tables)
        )
    else:
        sections.append(minimal_schema_context(max_tables=20))

    if concept_hint:
        sections.append(f"\n## 개념 매핑 (온톨로지)\n{concept_hint}")
    if join_hint:
        sections.append(join_hint)

    return "\n".join(sections)


def _augment_intermediate_tables(join_sql: str, all_tables: list[str]):
    """
    JOIN SQL에서 경유 테이블을 파싱해 ChromaDB에서 추가 문서 확보.
    (컨텍스트 직접 주입 대신 all_tables 리스트 보강)
    """
    import re
    for match in re.finditer(r"JOIN\s+(CIM_\w+)\s+WITH", join_sql):
        t = match.group(1)
        if t not in all_tables:
            all_tables.append(t)
