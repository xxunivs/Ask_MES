"""
스키마 벡터 검색, 온톨로지 개념 매핑, FK JOIN 힌트를 묶은 하이브리드 RAG 컨텍스트 생성
파이프라인 1단계 관련 테이블 찾기와 2단계 JOIN 경로 계산 담당
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


class OllamaEmbeddingFunction(embedding_functions.EmbeddingFunction):
    """Ollama 기반 Chroma 임베딩 함수, 영어 전용 기본 임베딩의 한국어 검색 품질 저하 대응"""

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


_BASE_DIR       = os.path.dirname(__file__)
SCHEMA_PATH     = os.path.join(_BASE_DIR, "../../data/mes_schema.json")
COLLECTION_NAME = "mes_schema"
HASH_FILE       = os.path.join(CHROMA_PATH, ".schema_hash")


_collection:     Optional[chromadb.Collection] = None
_fk_resolver:    Optional[FKPathResolver]       = None
_concept_engine = None


@dataclass(frozen=True)
class RetrievalConfig:
    """벤치마크 ablation용 RAG 구성"""
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
    """ChromaDB, FKPathResolver, 개념 엔진 초기화, 앱 시작 시 1회 호출"""
    global _collection, _fk_resolver, _concept_engine

    client = chromadb.PersistentClient(path=CHROMA_PATH)
    ef = _embedding_function()
    current_hash = _schema_hash()

    if current_hash != _saved_hash():
        print("[ChromaDB] 스키마 변경 감지 → 컬렉션 재생성 중...")
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        # Chroma 기본값이 L2라 코사인 거리 명시
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

    _fk_resolver = get_resolver(SCHEMA_PATH)

    _concept_engine = get_concept_engine()

    print("[Retriever] Ontology-Guided Hybrid RAG 초기화 완료")


def _seed_schema():
    """mes_schema.json의 테이블, 컬럼 단위 문서 ChromaDB 적재"""
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


def minimal_schema_context(max_tables: int = 40) -> str:
    """B0 베이스라인용 테이블 및 PK 목록"""
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
    """자연어 질의에 대한 프롬프트 주입용 하이브리드 RAG 컨텍스트"""
    cfg = config or RetrievalConfig()

    if not cfg.use_rag and not cfg.use_ontology and not cfg.use_fk:
        return minimal_schema_context()

    if _collection is None:
        init_chroma()

    k = n or RAG_TOP_K

    concept_tables: list[str] = []
    concept_hint:   str       = ""
    if cfg.use_ontology and _concept_engine:
        concept_tables = _concept_engine.find_tables(query)
        concept_hint   = _concept_engine.get_concept_hint(query)

    chroma_docs: list[str] = []
    chroma_tables: list[str] = []
    if cfg.use_rag:
        results  = _collection.query(query_texts=[query], n_results=k)
        chroma_docs   = results["documents"][0]
        chroma_metas  = results["metadatas"][0]

        for m in chroma_metas:
            t = m.get("table", "")
            if t and t not in chroma_tables:
                chroma_tables.append(t)

    # 온톨로지 개념 테이블 우선 배치
    all_tables: list[str] = list(concept_tables)
    for t in chroma_tables:
        if t not in all_tables:
            all_tables.append(t)

    join_hint = ""
    if cfg.use_fk and _fk_resolver and len(all_tables) >= 2:
        join_sql = _fk_resolver.get_join_sql(all_tables[:5], max_hops=4)
        if join_sql:
            join_hint = f"\n\n## JOIN 경로 힌트 (Dijkstra 최단경로)\n{join_sql}"
            _augment_intermediate_tables(join_sql, all_tables)

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
    """JOIN SQL의 경유 테이블로 all_tables 보강"""
    import re
    for match in re.finditer(r"JOIN\s+(CIM_\w+)\s+WITH", join_sql):
        t = match.group(1)
        if t not in all_tables:
            all_tables.append(t)
