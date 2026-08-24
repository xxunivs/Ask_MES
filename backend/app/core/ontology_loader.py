"""
app/core/ontology_loader.py
========================
OWL/Turtle 온톨로지(mes_ontology.ttl)를 로드해서 두 가지 역할을 수행:

  1. 개념 검색 (ConceptResolver)
     자연어 쿼리에서 skos:altLabel 매핑으로 관련 테이블/컬럼 식별
     → 자연어 개념어를 OWL 기반으로 테이블·컬럼에 매핑

  2. JOIN 힌트 추출 (OntologyJoinHinter)
     mfg:joinCondition 어노테이션에서 JOIN ON 절 직접 추출
     → FKPathResolver와 협업 (온톨로지 우선, FK 그래프 보완)

사용법:
  from app.core.ontology_loader import get_ontology
  onto = get_ontology()
  tables = onto.find_tables("홀드 상태인 LOT")
  join  = onto.get_join_hint(["CIM_LOT", "CIM_EQUIPMENTCLASS"])

설치:
  pip install rdflib
"""

import os
from functools import lru_cache
from typing import Optional

try:
    from rdflib import Graph, Namespace, URIRef, Literal
    from rdflib.namespace import RDF, RDFS, OWL, SKOS, XSD
    RDFLIB_OK = True
except ImportError:
    Graph = Namespace = URIRef = Literal = None
    RDF = RDFS = OWL = SKOS = XSD = None
    RDFLIB_OK = False

# ──────────────────────────────────────────────────────────────────
# 네임스페이스
# ──────────────────────────────────────────────────────────────────

MFG = Namespace("http://neurofactory.skku.ac.kr/mes#") if RDFLIB_OK else None

_BASE_DIR     = os.path.dirname(__file__)
ONTOLOGY_PATH = os.path.join(_BASE_DIR, "../../data/mes_ontology.ttl")


# ──────────────────────────────────────────────────────────────────
# OWL 기반 개념 리졸버
# ──────────────────────────────────────────────────────────────────

class OntologyEngine:
    """
    rdflib로 파싱한 OWL 그래프를 기반으로:
    - 자연어 개념어 → 테이블/컬럼 매핑
    - 클래스 간 ObjectProperty에서 JOIN 힌트 추출
    """

    def __init__(self, ttl_path: str):
        if not RDFLIB_OK:
            raise ImportError("rdflib가 설치되지 않았습니다: pip install rdflib")
        if not os.path.exists(ttl_path):
            raise FileNotFoundError(f"온톨로지 파일 없음: {ttl_path}")

        self._g = Graph()
        self._g.parse(ttl_path, format="turtle")
        print(f"[OntologyEngine] 파싱 완료: {len(self._g)} 트리플")

        # 사전 인덱스 구성
        self._alias_table:  dict[str, list[str]] = {}  # 개념어 → 테이블 목록
        self._alias_column: dict[str, list[str]] = {}  # 개념어 → 컬럼 목록
        self._join_index:   dict[tuple, str]     = {}  # (tbl_a, tbl_b) → JOIN 조건

        self._build_alias_index()
        self._build_join_index()

    # ── 인덱스 구성 ────────────────────────────────────────────────

    def _build_alias_index(self):
        """
        rdfs:label, skos:altLabel → mfg:mapsToTable / mfg:mapsToColumn 인덱싱
        """
        # 클래스 레벨: rdfs:label + skos:altLabel → mapsToTable
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

        # 데이터속성 레벨: rdfs:label + skos:altLabel → mapsToColumn
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
                    # 컬럼에서 테이블도 추출
                    tbl = str(col).split(".")[0] if "." in str(col) else ""
                    if tbl:
                        self._alias_table.setdefault(key, [])
                        if tbl not in self._alias_table[key]:
                            self._alias_table[key].append(tbl)

        print(f"[OntologyEngine] 별칭 인덱스: {len(self._alias_table)} 항목")

    def _build_join_index(self):
        """
        mfg:joinCondition 어노테이션에서 (src_table, dst_table) → JOIN 조건 추출
        """
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
                    # viaTable이 있으면 2-hop JOIN으로 처리
                    if via:
                        join_cond = f"[via {str(via[0])}] " + join_cond
                    self._join_index[key] = join_cond

        print(f"[OntologyEngine] JOIN 인덱스: {len(self._join_index)} 쌍")

    # ── 공개 API ──────────────────────────────────────────────────

    def find_tables(self, query: str) -> list[str]:
        """쿼리에서 관련 테이블 목록 반환"""
        q = query.lower()
        found: list[str] = []
        for alias, tables in self._alias_table.items():
            if alias in q:
                for t in tables:
                    if t not in found:
                        found.append(t)
        return found

    def find_columns(self, query: str) -> list[str]:
        """쿼리에서 관련 컬럼 목록 반환"""
        q = query.lower()
        found: list[str] = []
        for alias, columns in self._alias_column.items():
            if alias in q:
                for c in columns:
                    if c not in found:
                        found.append(c)
        return found

    def get_join_hint(self, tables: list[str]) -> str:
        """
        테이블 목록에서 온톨로지 기반 JOIN 힌트 문자열 반환.
        viaTable 포함 관계는 2-hop JOIN으로 표현.
        """
        hints: list[str] = []
        for i, t1 in enumerate(tables):
            for t2 in tables[i+1:]:
                key = tuple(sorted([t1, t2]))
                if key in self._join_index:
                    cond = self._join_index[key]
                    if cond.startswith("[via "):
                        # 경유 테이블 파싱
                        via_tbl = cond.split("]")[0].replace("[via ", "").strip()
                        raw     = cond.split("] ")[1]
                        # AND로 분리
                        parts = [p.strip() for p in raw.split("AND")]
                        for part in parts:
                            hint = f"JOIN {part.split('=')[1].strip().split('.')[0]} WITH (NOLOCK) ON {part.strip()}"
                            if hint not in hints:
                                hints.append(hint)
                    else:
                        dst = cond.split("=")[1].strip().split(".")[0]
                        hint = f"JOIN {dst} WITH (NOLOCK) ON {cond}"
                        if hint not in hints:
                            hints.append(hint)
        return "\n".join(hints)

    def get_concept_hint(self, query: str) -> str:
        """프롬프트 주입용 개념 힌트 문자열"""
        tables  = self.find_tables(query)
        columns = self.find_columns(query)
        lines = []
        if tables:
            lines.append(f"관련 테이블: {', '.join(tables)}")
        if columns:
            lines.append(f"관련 컬럼: {', '.join(columns)}")
        return "\n".join(lines)

    def sparql(self, query: str):
        """SPARQL 쿼리 실행 (디버그/확장용)"""
        return self._g.query(query)

    def stats(self) -> dict:
        return {
            "triples":     len(self._g),
            "classes":     len(list(self._g.subjects(RDF.type, OWL.Class))),
            "obj_props":   len(list(self._g.subjects(RDF.type, OWL.ObjectProperty))),
            "data_props":  len(list(self._g.subjects(RDF.type, OWL.DatatypeProperty))),
            "alias_index": len(self._alias_table),
            "join_index":  len(self._join_index),
        }


# ──────────────────────────────────────────────────────────────────
# 싱글턴
# ──────────────────────────────────────────────────────────────────

_engine_instance: Optional[OntologyEngine] = None


def get_ontology(ttl_path: str = None) -> OntologyEngine:
    """OntologyEngine 싱글턴 반환"""
    global _engine_instance
    if _engine_instance is None:
        path = ttl_path or ONTOLOGY_PATH
        _engine_instance = OntologyEngine(path)
    return _engine_instance


def get_concept_engine(ttl_path: str = None):
    """온톨로지(.ttl) 기반 개념 엔진을 반환한다."""
    return get_ontology(ttl_path)


# ──────────────────────────────────────────────────────────────────
# 단독 실행 테스트
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    ttl = os.path.join(os.path.dirname(__file__), "../../data/mes_ontology.ttl")
    if not os.path.exists(ttl):
        ttl = "data/mes_ontology.ttl"

    print("\n" + "="*60)
    print("  OntologyEngine 로드 테스트")
    print("="*60)

    engine = OntologyEngine(ttl)
    print("\n  통계:", engine.stats())

    test_queries = [
        "홀드 상태인 LOT 목록",
        "설비 분류별 설비 수",
        "불량률이 높은 LOT",
        "납기일이 지난 작업지시",
        "자재 만료일 확인",
        "PM 대상 설비 보여줘",
        "track in 시간 기준으로 오늘 투입된 LOT",
        "외주 작업지시 목록",
    ]

    print("\n  ─── 개념 검색 테스트 ───")
    for q in test_queries:
        tables  = engine.find_tables(q)
        columns = engine.find_columns(q)
        print(f"\n  Q: {q}")
        print(f"     테이블: {tables}")
        print(f"     컬럼:   {columns[:5]}")

    print("\n  ─── JOIN 힌트 테스트 ───")
    join_tests = [
        ["CIM_LOT", "CIM_EQUIPMENT"],
        ["CIM_LOT", "CIM_EQUIPMENTCLASS"],
        ["CIM_MATERIALLOT", "CIM_MATERIALCLASS"],
        ["CIM_LOT", "CIM_BATCH"],   # viaTable 케이스
        ["CIM_LOT", "CIM_MATERIALLOT"],  # viaTable 케이스
    ]
    for tables in join_tests:
        hint = engine.get_join_hint(tables)
        print(f"\n  {tables}")
        if hint:
            for line in hint.split("\n"):
                print(f"    {line}")
        else:
            print("    (직접 JOIN 없음 → FKResolver 위임)")

    # SPARQL 샘플
    print("\n  ─── SPARQL 테스트 ───")
    result = engine.sparql("""
        PREFIX mfg: <http://neurofactory.skku.ac.kr/mes#>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        SELECT ?class ?table ?alias WHERE {
            ?class mfg:mapsToTable ?table .
            OPTIONAL { ?class skos:altLabel ?alias . FILTER(lang(?alias)="ko") }
        }
        ORDER BY ?table
        LIMIT 15
    """)
    for row in result:
        print(f"    {str(row.table):30s}  alias={row.alias}")
