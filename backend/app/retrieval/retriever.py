import hashlib
import os
from dataclasses import dataclass

import chromadb
import httpx
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
from app.retrieval.ontology_loader import OntologyEngine, get_ontology
from app.schema import SCHEMA_PATH, schema_tables


# HTTP 연결 재사용 (질문마다 새 연결 방지)
class OllamaEmbeddingFunction(embedding_functions.EmbeddingFunction):
    def __init__(self, model: str, base_url: str):
        self._model = model
        self._url = f"{base_url.rstrip('/')}/api/embeddings"
        self._client = httpx.Client(timeout=120.0)

    def name(self) -> str:
        return f"ollama-{self._model}"

    def __call__(self, input):
        vectors = []
        for text in input:
            resp = self._client.post(self._url, json={"model": self._model, "prompt": text})
            resp.raise_for_status()
            vectors.append(resp.json()["embedding"])
        return vectors


class DeepInfraEmbeddingFunction(embedding_functions.EmbeddingFunction):
    def __init__(self, model: str):
        self._model = model
        self._client = httpx.Client(timeout=120.0)

    def name(self) -> str:
        return f"deepinfra-{self._model}"

    def __call__(self, input):
        vectors = []
        for i in range(0, len(input), 64):
            resp = self._client.post(
                f"{DEEPINFRA_URL}/embeddings",
                json={"model": self._model, "input": list(input[i : i + 64])},
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


COLLECTION_NAME = "mes_schema"
HASH_FILE = os.path.join(CHROMA_PATH, ".schema_hash")

_collection: chromadb.Collection | None = None
_fk_resolver: FKPathResolver | None = None
_concept_engine: OntologyEngine | None = None


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


# 스키마, 임베딩 모델 변경 시 색인 재생성
def _schema_hash() -> str:
    return f"{hashlib.md5(SCHEMA_PATH.read_bytes()).hexdigest()}:{EMBED_BACKEND}:{EMBED_MODEL}"


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
    options = {
        "name": COLLECTION_NAME,
        "embedding_function": _embedding_function(),
        # 코사인 거리 (Chroma 기본값 L2)
        "metadata": {"hnsw:space": "cosine"},
    }
    current_hash = _schema_hash()

    if current_hash != _saved_hash():
        print("[ChromaDB] 스키마 또는 임베딩 변경, 색인 재생성")
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        _collection = client.create_collection(**options)
    else:
        _collection = client.get_or_create_collection(**options)

    if _collection.count() == 0:
        _seed_schema()
        _save_hash(current_hash)
    print(f"[ChromaDB] 문서 {_collection.count()}개")

    _fk_resolver = get_resolver()
    _concept_engine = get_ontology()


def _seed_schema():
    docs, ids, metas = [], [], []
    for table in schema_tables():
        name = table["name"]
        columns = ", ".join(f"{c['name']}({c.get('type', '')})" for c in table.get("columns", []))
        doc = f"[테이블] {name}\n설명: {table.get('description', '')}\n컬럼: {columns}"
        if table.get("foreign_keys"):
            doc += "\nFK: " + ", ".join(
                f"{fk['column']} → {fk['ref_table']}.{fk['ref_column']}" for fk in table["foreign_keys"]
            )
        docs.append(doc)
        ids.append(f"tbl_{name}")
        metas.append({"type": "table", "table": name})

        for col in table.get("columns", []):
            docs.append(f"[컬럼] {name}.{col['name']} ({col.get('type', '')})\n설명: {col.get('description', '')}")
            ids.append(f"col_{name}_{col['name']}")
            metas.append({"type": "column", "table": name, "column": col["name"]})

    for i in range(0, len(docs), 500):
        _collection.add(documents=docs[i : i + 500], ids=ids[i : i + 500], metadatas=metas[i : i + 500])


def minimal_schema_context(max_tables: int = 40) -> str:
    lines = ["[MES 테이블 목록]"]
    for table in schema_tables()[:max_tables]:
        pk = ", ".join(table.get("pk") or [])
        lines.append(f"- {table['name']}" + (f" (PK: {pk})" if pk else ""))
    return "\n".join(lines)


def retrieve_context(query: str, n: int | None = None, config: RetrievalConfig | None = None) -> str:
    cfg = config or RetrievalConfig()
    if not (cfg.use_rag or cfg.use_ontology or cfg.use_fk):
        return minimal_schema_context()
    if _collection is None:
        init_chroma()

    concept_tables: list[str] = []
    concept_hint = ""
    if cfg.use_ontology and _concept_engine:
        concept_tables = _concept_engine.find_tables(query)
        concept_hint = _concept_engine.get_concept_hint(query)

    docs: list[str] = []
    searched_tables: list[str] = []
    if cfg.use_rag:
        results = _collection.query(query_texts=[query], n_results=n or RAG_TOP_K)
        docs = results["documents"][0]
        # 컬럼 하나만 걸린 테이블: JOIN 경로 계산 제외
        hits: dict[str, int] = {}
        for meta in results["metadatas"][0]:
            if meta.get("table"):
                hits[meta["table"]] = hits.get(meta["table"], 0) + (2 if meta.get("type") == "table" else 1)
        searched_tables = [t for t, count in hits.items() if count >= 2]

    tables = concept_tables + [t for t in searched_tables if t not in concept_tables]
    join_sql = ""
    if cfg.use_fk and _fk_resolver and len(tables) >= 2:
        join_sql = _fk_resolver.get_join_sql(tables[:5], max_hops=4)

    if docs:
        sections = ["\n---\n".join(docs)]
    elif concept_tables:
        sections = ["[개념 사전으로 찾은 테이블] " + ", ".join(concept_tables)]
    else:
        sections = [minimal_schema_context(max_tables=20)]
    if concept_hint:
        sections.append(f"\n## 개념 매핑 (온톨로지)\n{concept_hint}")
    if join_sql:
        sections.append(f"\n\n## JOIN 경로 힌트 (Dijkstra 최단경로)\n{join_sql}")
    return "\n".join(sections)
