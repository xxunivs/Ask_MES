import os
from typing import Optional

try:
    from rdflib import Graph, Namespace, URIRef, Literal
    from rdflib.namespace import RDF, RDFS, OWL, SKOS, XSD
    RDFLIB_OK = True
except ImportError:
    Graph = Namespace = URIRef = Literal = None
    RDF = RDFS = OWL = SKOS = XSD = None
    RDFLIB_OK = False

MFG = Namespace("http://neurofactory.skku.ac.kr/mes#") if RDFLIB_OK else None

_BASE_DIR     = os.path.dirname(__file__)
ONTOLOGY_PATH = os.path.join(_BASE_DIR, "../../data/mes_ontology.ttl")


class OntologyEngine:

    def __init__(self, ttl_path: str):
        if not RDFLIB_OK:
            raise ImportError("rdflib가 설치되지 않았습니다: pip install rdflib")
        if not os.path.exists(ttl_path):
            raise FileNotFoundError(f"온톨로지 파일 없음: {ttl_path}")

        self._g = Graph()
        self._g.parse(ttl_path, format="turtle")
        print(f"[OntologyEngine] 파싱 완료: {len(self._g)} 트리플")

        self._alias_table:  dict[str, list[str]] = {}
        self._alias_column: dict[str, list[str]] = {}
        self._join_index:   dict[tuple, str]     = {}

        self._build_alias_index()
        self._build_join_index()

    def _build_alias_index(self):
        for cls in self._g.subjects(RDF.type, OWL.Class):
            labels = list(self._g.objects(cls, RDFS.label)) + \
                     list(self._g.objects(cls, SKOS.altLabel))
            tables = list(self._g.objects(cls, MFG.mapsToTable))
            for label in labels:
                key = str(label).lower()
                for tbl in tables:
                    self._alias_table.setdefault(key, [])
                    if str(tbl) not in self._alias_table[key]:
                        self._alias_table[key].append(str(tbl))

        for prop in self._g.subjects(RDF.type, OWL.DatatypeProperty):
            labels  = list(self._g.objects(prop, RDFS.label)) + \
                      list(self._g.objects(prop, SKOS.altLabel))
            columns = list(self._g.objects(prop, MFG.mapsToColumn))
            for label in labels:
                key = str(label).lower()
                for col in columns:
                    self._alias_column.setdefault(key, [])
                    if str(col) not in self._alias_column[key]:
                        self._alias_column[key].append(str(col))
                    tbl = str(col).split(".")[0] if "." in str(col) else ""
                    if tbl:
                        self._alias_table.setdefault(key, [])
                        if tbl not in self._alias_table[key]:
                            self._alias_table[key].append(tbl)

        print(f"[OntologyEngine] 별칭 인덱스: {len(self._alias_table)} 항목")

    def _build_join_index(self):
        for prop in self._g.subjects(RDF.type, OWL.ObjectProperty):
            domain_list = list(self._g.objects(prop, RDFS.domain))
            range_list  = list(self._g.objects(prop, RDFS.range))
            joins       = list(self._g.objects(prop, MFG.joinCondition))
            via         = list(self._g.objects(prop, MFG.viaTable))

            if not domain_list or not range_list or not joins:
                continue

            src_tables = [str(self._g.value(d, MFG.mapsToTable))
                          for d in domain_list
                          if self._g.value(d, MFG.mapsToTable)]
            dst_tables = [str(self._g.value(r, MFG.mapsToTable))
                          for r in range_list
                          if self._g.value(r, MFG.mapsToTable)]

            for src in src_tables:
                for dst in dst_tables:
                    key = tuple(sorted([src, dst]))
                    join_cond = str(joins[0])
                    if via:
                        join_cond = f"[via {str(via[0])}] " + join_cond
                    self._join_index[key] = join_cond

        print(f"[OntologyEngine] JOIN 인덱스: {len(self._join_index)} 쌍")

    def find_tables(self, query: str) -> list[str]:
        q = query.lower()
        found: list[str] = []
        for alias, tables in self._alias_table.items():
            if alias in q:
                for t in tables:
                    if t not in found:
                        found.append(t)
        return found

    def find_columns(self, query: str) -> list[str]:
        q = query.lower()
        found: list[str] = []
        for alias, columns in self._alias_column.items():
            if alias in q:
                for c in columns:
                    if c not in found:
                        found.append(c)
        return found


    def get_concept_hint(self, query: str) -> str:
        tables  = self.find_tables(query)
        columns = self.find_columns(query)
        lines = []
        if tables:
            lines.append(f"관련 테이블: {', '.join(tables)}")
        if columns:
            lines.append(f"관련 컬럼: {', '.join(columns)}")
        return "\n".join(lines)


    def stats(self) -> dict:
        return {
            "triples":     len(self._g),
            "classes":     len(list(self._g.subjects(RDF.type, OWL.Class))),
            "obj_props":   len(list(self._g.subjects(RDF.type, OWL.ObjectProperty))),
            "data_props":  len(list(self._g.subjects(RDF.type, OWL.DatatypeProperty))),
            "alias_index": len(self._alias_table),
            "join_index":  len(self._join_index),
        }


_engine_instance: Optional[OntologyEngine] = None


def get_ontology(ttl_path: str = None) -> OntologyEngine:
    global _engine_instance
    if _engine_instance is None:
        path = ttl_path or ONTOLOGY_PATH
        _engine_instance = OntologyEngine(path)
    return _engine_instance


def get_concept_engine(ttl_path: str = None):
    return get_ontology(ttl_path)
