import hashlib
import json
import os
from typing import Optional

from dataclasses import dataclass

import chromadb
from chromadb.utils import embedding_functions

from app.config import (
    CHROMA_PATH,
    DEEPINFRA_API_KEY,
    DEEPINFRA_URL,
    EMBED_BACKEND,
    EMBED_MODEL,
    OLLAMA_URL,
    RAG_TOP_K,
)
from app.retrieval.fk_resolver import FKPathResolver, get_resolver
from app.retrieval.ontology_loader import get_concept_engine


class OllamaEmbeddingFunction(embedding_functions.EmbeddingFunction):

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


class DeepInfraEmbeddingFunction(embedding_functions.EmbeddingFunction):

    def __init__(self, model: str):
        import httpx

        self._model = model
        # 질문마다 TLS 연결을 새로 맺지 않도록 연결 재사용
        self._client = httpx.Client(timeout=120.0)

    def name(self) -> str:
        return f"deepinfra-{self._model}"

    def __call__(self, input):
        vectors = []
        for i in range(0, len(input), 64):
            resp = self._client.post(
                f"{DEEPINFRA_URL}/embeddings",
                json={"model": self._model, "input": list(input[i:i + 64])},
                headers={"Authorization": f"Bearer {DEEPINFRA_API_KEY}"},
            )
            resp.raise_for_status()
            vectors.extend(d["embedding"] for d in resp.json()["data"])
        return vectors


def _embedding_function():
    if EMBED_BACKEND == "ollama":
        return OllamaEmbeddingFunction(EMBED_MODEL, OLLAMA_URL)
    if EMBED_BACKEND == "deepinfra":
        return DeepInfraEmbeddingFunction(EMBED_MODEL)
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
    # 임베딩 방식이 바뀌면 기존 벡터와 섞이지 않도록 색인 재생성
    with open(SCHEMA_PATH, "rb") as f:
        return f"{hashlib.md5(f.read()).hexdigest()}:{EMBED_BACKEND}:{EMBED_MODEL}"


def _saved_hash() -> str:
    if os.path.exists(HASH_FILE):
        return open(HASH_FILE).read().strip()
    return ""


def _save_hash(h: str):
    os.makedirs(CHROMA_PATH, exist_ok=True)
    with open(HASH_FILE, "w") as f:
        f.write(h)


def init_chroma():
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

        # 컬럼 하나만 걸린 테이블은 JOIN 경로 계산 제외
        hits: dict[str, int] = {}
        for m in chroma_metas:
            t = m.get("table", "")
            if t:
                hits[t] = hits.get(t, 0) + (2 if m.get("type") == "table" else 1)
        chroma_tables = [t for t, c in hits.items() if c >= 2]

    all_tables: list[str] = list(concept_tables)
    for t in chroma_tables:
        if t not in all_tables:
            all_tables.append(t)

    join_hint = ""
    if cfg.use_fk and _fk_resolver and len(all_tables) >= 2:
        join_sql = _fk_resolver.get_join_sql(all_tables[:5], max_hops=4)
        if join_sql:
            join_hint = f"\n\n## JOIN 경로 힌트 (Dijkstra 최단경로)\n{join_sql}"

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
