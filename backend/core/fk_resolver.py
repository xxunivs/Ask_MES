"""
core/fk_resolver.py
====================
MES 스키마 FK 관계를 방향 그래프로 모델링하고
Dijkstra 알고리즘으로 테이블 간 최단 JOIN 경로를 계산합니다.

아키텍처 위치:
  NL Query
    → ChromaDB (관련 테이블 식별)
    → FKPathResolver (테이블 간 JOIN 경로 계산)  ← 이 모듈
    → Prompt 구성 (스키마 컨텍스트 + JOIN 힌트)
    → Ollama LLM (SQL 생성)

사용 예:
  resolver = FKPathResolver("data/mes_schema.json")
  path = resolver.shortest_join_path("CIM_LOT", "CIM_EQUIPMENTCLASS")
  # → [{"from":"CIM_LOT","to":"CIM_EQUIPMENT","on":"CIM_LOT.EQUIPMENTID = CIM_EQUIPMENT.EQUIPMENTID"},
  #    {"from":"CIM_EQUIPMENT","to":"CIM_EQUIPMENTCLASS","on":"CIM_EQUIPMENT.EQUIPMENTCLASSID = CIM_EQUIPMENTCLASS.EQUIPMENTCLASSID"}]

  sql_joins = resolver.get_join_sql(["CIM_LOT","CIM_EQUIPMENTCLASS"])
  # → "JOIN CIM_EQUIPMENT WITH (NOLOCK) ON CIM_LOT.EQUIPMENTID = CIM_EQUIPMENT.EQUIPMENTID\n
  #    JOIN CIM_EQUIPMENTCLASS WITH (NOLOCK) ON CIM_EQUIPMENT.EQUIPMENTCLASSID = CIM_EQUIPMENTCLASS.EQUIPMENTCLASSID"
"""

import heapq
import json
import os
from dataclasses import dataclass, field
from typing import Optional

# ──────────────────────────────────────────────────────────────────
# 데이터 구조
# ──────────────────────────────────────────────────────────────────

@dataclass
class FKEdge:
    """FK 관계 엣지 하나를 나타냄"""
    src_table:  str   # 출발 테이블
    dst_table:  str   # 도착 테이블
    src_col:    str   # 출발 테이블의 FK 컬럼
    dst_col:    str   # 도착 테이블의 참조 컬럼
    weight:     int = 1   # 기본 홉 비용 (추후 확장 가능)

    @property
    def join_condition(self) -> str:
        return f"{self.src_table}.{self.src_col} = {self.dst_table}.{self.dst_col}"

    @property
    def join_clause(self) -> str:
        return f"JOIN {self.dst_table} WITH (NOLOCK) ON {self.join_condition}"


@dataclass(order=True)
class _HeapItem:
    """heapq용 우선순위 래퍼 (path는 비교 제외)"""
    cost: int
    node: str
    path: list = field(compare=False, default_factory=list)


# ──────────────────────────────────────────────────────────────────
# FK 그래프 + Dijkstra
# ──────────────────────────────────────────────────────────────────

class FKPathResolver:
    """
    mes_schema.json의 FK 관계를 무방향 가중치 그래프로 모델링.
    Dijkstra 알고리즘으로 두 테이블 간 최단 JOIN 경로를 반환.
    """

    def __init__(self, schema_path: str):
        self._graph: dict[str, list[FKEdge]] = {}
        self._all_tables: set[str] = set()
        self._load(schema_path)
        print(f"[FKResolver] 그래프 구성 완료: "
              f"{self._all_tables.__len__()} 테이블, "
              f"{sum(len(v) for v in self._graph.values()) // 2} FK 엣지")

    # ── 그래프 구성 ──────────────────────────────────────────────

    def _add_edge(self, edge: FKEdge):
        """양방향 엣지 추가"""
        # 정방향
        self._graph.setdefault(edge.src_table, []).append(edge)
        # 역방향 (JOIN은 양방향으로 탐색 가능)
        reverse = FKEdge(
            src_table=edge.dst_table,
            dst_table=edge.src_table,
            src_col=edge.dst_col,
            dst_col=edge.src_col,
            weight=edge.weight,
        )
        self._graph.setdefault(edge.dst_table, []).append(reverse)

    def _load(self, schema_path: str):
        """mes_schema.json에서 FK 관계를 읽어 그래프 구성"""
        if not os.path.exists(schema_path):
            raise FileNotFoundError(f"스키마 파일 없음: {schema_path}")

        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)

        for table in schema.get("tables", []):
            tname = table["name"]
            self._all_tables.add(tname)
            self._graph.setdefault(tname, [])

            for fk in table.get("foreign_keys", []):
                # 자기 참조 제외 (SUBPROCESSDEFINITIONID 같은 케이스)
                if fk["ref_table"] == tname:
                    continue
                edge = FKEdge(
                    src_table=tname,
                    dst_table=fk["ref_table"],
                    src_col=fk["column"],
                    dst_col=fk["ref_column"],
                )
                self._add_edge(edge)

    # ── Dijkstra ─────────────────────────────────────────────────

    def shortest_join_path(
        self, src: str, dst: str
    ) -> list[dict]:
        """
        src 테이블에서 dst 테이블까지의 최단 JOIN 경로 반환.

        Returns:
            [{"from": str, "to": str, "on": str, "join_clause": str}, ...]
            경로가 없으면 빈 리스트.
        """
        if src == dst:
            return []
        if src not in self._all_tables or dst not in self._all_tables:
            return []

        # Dijkstra
        heap = [_HeapItem(cost=0, node=src, path=[])]
        visited: set[str] = set()

        while heap:
            item = heapq.heappop(heap)

            if item.node in visited:
                continue
            visited.add(item.node)

            if item.node == dst:
                return item.path

            for edge in self._graph.get(item.node, []):
                if edge.dst_table not in visited:
                    step = {
                        "from":        edge.src_table,
                        "to":          edge.dst_table,
                        "on":          edge.join_condition,
                        "join_clause": edge.join_clause,
                    }
                    heapq.heappush(heap, _HeapItem(
                        cost=item.cost + edge.weight,
                        node=edge.dst_table,
                        path=item.path + [step],
                    ))

        return []   # 연결 불가

    # ── 다중 테이블 JOIN SQL 생성 ─────────────────────────────────

    def get_join_sql(self, tables: list[str], max_hops: int = 4) -> str:
        """
        테이블 목록을 받아 체인 JOIN SQL 힌트 문자열 반환.

        tables: ChromaDB가 식별한 관련 테이블 목록 (우선순위 순)
        max_hops: 경로 탐색 최대 홉 수 (긴 경로는 프롬프트 오염 방지)

        Returns:
            "JOIN CIM_EQUIPMENT WITH (NOLOCK) ON ...\n
             JOIN CIM_EQUIPMENTCLASS WITH (NOLOCK) ON ..."
        """
        if len(tables) < 2:
            return ""

        seen_pairs: set[tuple] = set()
        join_clauses: list[str] = []

        # 앵커 테이블(첫 번째)에서 나머지 테이블까지 각각 경로 탐색
        anchor = tables[0]
        for target in tables[1:]:
            pair = tuple(sorted([anchor, target]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            path = self.shortest_join_path(anchor, target)
            if not path:
                # anchor에서 못 찾으면 인접 탐색
                for prev in tables:
                    if prev == target:
                        continue
                    path = self.shortest_join_path(prev, target)
                    if path:
                        break

            if path and len(path) <= max_hops:
                for step in path:
                    clause = step["join_clause"]
                    if clause not in join_clauses:
                        join_clauses.append(clause)

        return "\n".join(join_clauses)

    # ── 디버그 유틸 ──────────────────────────────────────────────

    def describe_path(self, src: str, dst: str) -> str:
        """경로를 사람이 읽기 쉬운 형식으로 반환 (디버그용)"""
        path = self.shortest_join_path(src, dst)
        if not path:
            return f"[FKResolver] {src} → {dst} : 경로 없음"
        steps = " → ".join(
            f"{s['from']} --[{s['on'].split('=')[0].strip().split('.')[-1]}]--> {s['to']}"
            for s in path
        )
        return f"[FKResolver] {src} → {dst} ({len(path)}홉): {steps}"

    def neighbors(self, table: str) -> list[str]:
        """특정 테이블과 직접 연결된 테이블 목록"""
        return [e.dst_table for e in self._graph.get(table, [])]

    def all_tables(self) -> set[str]:
        return set(self._all_tables)


# ──────────────────────────────────────────────────────────────────
# 싱글턴 (앱 전역 1회 초기화)
# ──────────────────────────────────────────────────────────────────

_resolver_instance: Optional[FKPathResolver] = None


def get_resolver(schema_path: str = None) -> FKPathResolver:
    """
    FKPathResolver 싱글턴 반환.
    main.py lifespan 또는 retriever.init_chroma() 에서 최초 1회 호출.
    """
    global _resolver_instance
    if _resolver_instance is None:
        if schema_path is None:
            schema_path = os.path.join(
                os.path.dirname(__file__), "../data/mes_schema.json"
            )
        _resolver_instance = FKPathResolver(schema_path)
    return _resolver_instance


# ──────────────────────────────────────────────────────────────────
# 단독 실행 — 경로 확인 테스트
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    schema = os.path.join(os.path.dirname(__file__), "../data/mes_schema.json")
    if not os.path.exists(schema):
        schema = "data/mes_schema.json"

    resolver = FKPathResolver(schema)

    # 기본 테스트 케이스
    test_pairs = [
        ("CIM_LOT",            "CIM_EQUIPMENTCLASS"),   # 2홉
        ("CIM_LOT",            "CIM_PRODUCTCLASS"),      # 2홉
        ("CIM_MATERIALLOT",    "CIM_MATERIALCLASS"),     # 1홉
        ("CIM_LOT",            "CIM_PROCESSNODE"),       # 1홉
        ("CIM_PRODUCTORDER",   "CIM_PRODUCTCLASS"),      # 1홉
        ("CIM_LOT",            "CIM_FACILITY"),          # 2홉 (via EQUIPMENT)
        ("CIM_PROCESSNODE",    "CIM_PROCESSSEGMENT"),    # 1홉
        ("CIM_LOT",            "CIM_MATERIALDEFINITION"),# 연결 없음 확인
    ]

    print("\n" + "="*65)
    print("  FKPathResolver 경로 테스트")
    print("="*65)
    for src, dst in test_pairs:
        print(f"\n  {resolver.describe_path(src, dst)}")
        path = resolver.shortest_join_path(src, dst)
        if path:
            for step in path:
                print(f"    {step['join_clause']}")

    # 커맨드라인 인수 처리
    if len(sys.argv) >= 3:
        src, dst = sys.argv[1], sys.argv[2]
        print(f"\n{'='*65}")
        print(f"  사용자 입력: {src} → {dst}")
        print("="*65)
        print(resolver.describe_path(src, dst))
        for step in resolver.shortest_join_path(src, dst):
            print(f"  {step['join_clause']}")

    # 다중 테이블 JOIN SQL 생성 테스트
    print(f"\n{'='*65}")
    print("  다중 테이블 JOIN SQL 생성 테스트")
    print("="*65)
    test_groups = [
        ["CIM_LOT", "CIM_EQUIPMENT", "CIM_EQUIPMENTCLASS"],
        ["CIM_LOT", "CIM_PRODUCTORDER", "CIM_PRODUCTDEFINITION"],
        ["CIM_MATERIALLOT", "CIM_MATERIALDEFINITION", "CIM_MATERIALCLASS"],
    ]
    for tables in test_groups:
        print(f"\n  입력 테이블: {tables}")
        sql = resolver.get_join_sql(tables)
        if sql:
            for line in sql.split("\n"):
                print(f"    {line}")
        else:
            print("    (JOIN 경로 없음)")
