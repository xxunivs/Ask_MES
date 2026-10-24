from __future__ import annotations

from pathlib import Path

from rdflib import Graph, Namespace
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from app.config import DATA_DIR

ONTOLOGY_PATH = DATA_DIR / "mes_ontology.ttl"
MFG = Namespace("http://neurofactory.skku.ac.kr/mes#")


def _add(index: dict[str, list[str]], key: str, value: str) -> None:
    values = index.setdefault(key, [])
    if value not in values:
        values.append(value)


def _find(index: dict[str, list[str]], query: str) -> list[str]:
    q = query.lower()
    found: list[str] = []
    for alias, values in index.items():
        if alias in q:
            found += [v for v in values if v not in found]
    return found


# 현장 용어(라벨, 별칭) -> 테이블, 컬럼
class OntologyEngine:
    def __init__(self, ttl_path: Path):
        graph = Graph()
        graph.parse(ttl_path, format="turtle")
        self._alias_table: dict[str, list[str]] = {}
        self._alias_column: dict[str, list[str]] = {}

        for cls in graph.subjects(RDF.type, OWL.Class):
            tables = [str(t) for t in graph.objects(cls, MFG.mapsToTable)]
            for label in self._labels(graph, cls):
                for table in tables:
                    _add(self._alias_table, label, table)

        for prop in graph.subjects(RDF.type, OWL.DatatypeProperty):
            columns = [str(c) for c in graph.objects(prop, MFG.mapsToColumn)]
            for label in self._labels(graph, prop):
                for column in columns:
                    _add(self._alias_column, label, column)
                    if "." in column:
                        _add(self._alias_table, label, column.split(".")[0])

        print(f"[Ontology] 트리플 {len(graph)}개, 현장 용어 {len(self._alias_table)}개")

    @staticmethod
    def _labels(graph: Graph, node) -> list[str]:
        return [str(x).lower() for x in [*graph.objects(node, RDFS.label), *graph.objects(node, SKOS.altLabel)]]

    def find_tables(self, query: str) -> list[str]:
        return _find(self._alias_table, query)

    def find_columns(self, query: str) -> list[str]:
        return _find(self._alias_column, query)

    def get_concept_hint(self, query: str) -> str:
        lines = []
        if tables := self.find_tables(query):
            lines.append(f"관련 테이블: {', '.join(tables)}")
        if columns := self.find_columns(query):
            lines.append(f"관련 컬럼: {', '.join(columns)}")
        return "\n".join(lines)


_engine: OntologyEngine | None = None


def get_ontology() -> OntologyEngine:
    global _engine
    if _engine is None:
        _engine = OntologyEngine(ONTOLOGY_PATH)
    return _engine
