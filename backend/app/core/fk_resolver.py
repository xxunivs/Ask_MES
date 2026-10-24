"""
MES 스키마 FK 관계 그래프와 Dijkstra 기반 테이블 간 최단 JOIN 경로 계산
파이프라인 2단계 JOIN 경로 계산 담당
"""

import heapq
import json
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FKEdge:
    """FK 관계 엣지"""
    src_table:  str
    dst_table:  str
    src_col:    str
    dst_col:    str
    weight:     int = 1

    @property
    def join_condition(self) -> str:
        return f"{self.src_table}.{self.src_col} = {self.dst_table}.{self.dst_col}"

    @property
    def join_clause(self) -> str:
        return f"JOIN {self.dst_table} WITH (NOLOCK) ON {self.join_condition}"


@dataclass(order=True)
class _HeapItem:
    """heapq용 우선순위 래퍼, path는 비교 제외"""
    cost: int
    node: str
    path: list = field(compare=False, default_factory=list)


class FKPathResolver:
    """mes_schema.json FK 관계의 무방향 가중치 그래프와 최단 JOIN 경로 탐색"""

    def __init__(self, schema_path: str):
        self._graph: dict[str, list[FKEdge]] = {}
        self._all_tables: set[str] = set()
        self._load(schema_path)
        print(f"[FKResolver] 그래프 구성 완료: "
              f"{self._all_tables.__len__()} 테이블, "
              f"{sum(len(v) for v in self._graph.values()) // 2} FK 엣지")

    def _add_edge(self, edge: FKEdge):
        self._graph.setdefault(edge.src_table, []).append(edge)
        # JOIN은 양쪽 방향 모두 가능하므로 역방향 엣지도 추가
        reverse = FKEdge(
            src_table=edge.dst_table,
            dst_table=edge.src_table,
            src_col=edge.dst_col,
            dst_col=edge.src_col,
            weight=edge.weight,
        )
        self._graph.setdefault(edge.dst_table, []).append(reverse)

    def _load(self, schema_path: str):
        if not os.path.exists(schema_path):
            raise FileNotFoundError(f"스키마 파일 없음: {schema_path}")

        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)

        for table in schema.get("tables", []):
            tname = table["name"]
            self._all_tables.add(tname)
            self._graph.setdefault(tname, [])

            for fk in table.get("foreign_keys", []):
                # SUBPROCESSDEFINITIONID 같은 자기 참조는 JOIN 경로에 무의미
                if fk["ref_table"] == tname:
                    continue
                edge = FKEdge(
                    src_table=tname,
                    dst_table=fk["ref_table"],
                    src_col=fk["column"],
                    dst_col=fk["ref_column"],
                )
                self._add_edge(edge)

    def shortest_join_path(
        self, src: str, dst: str
    ) -> list[dict]:
        """src에서 dst까지 최단 JOIN 경로 단계 목록, 경로 없으면 빈 리스트"""
        if src == dst:
            return []
        if src not in self._all_tables or dst not in self._all_tables:
            return []

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

        return []

    def get_join_sql(self, tables: list[str], max_hops: int = 4) -> str:
        """우선순위순 테이블 목록의 체인 JOIN 절 힌트, max_hops 초과 경로는 프롬프트 오염 방지로 제외"""
        if len(tables) < 2:
            return ""

        seen_pairs: set[tuple] = set()
        join_clauses: list[str] = []

        anchor = tables[0]
        for target in tables[1:]:
            pair = tuple(sorted([anchor, target]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            path = self.shortest_join_path(anchor, target)
            if not path:
                # 앵커와 연결이 없으면 다른 입력 테이블에서 경로 탐색
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

    def describe_path(self, src: str, dst: str) -> str:
        """디버그용 경로 설명 문자열"""
        path = self.shortest_join_path(src, dst)
        if not path:
            return f"[FKResolver] {src} → {dst} : 경로 없음"
        steps = " → ".join(
            f"{s['from']} --[{s['on'].split('=')[0].strip().split('.')[-1]}]--> {s['to']}"
            for s in path
        )
        return f"[FKResolver] {src} → {dst} ({len(path)}홉): {steps}"

    def neighbors(self, table: str) -> list[str]:
        return [e.dst_table for e in self._graph.get(table, [])]

    def all_tables(self) -> set[str]:
        return set(self._all_tables)


_resolver_instance: Optional[FKPathResolver] = None


def get_resolver(schema_path: str = None) -> FKPathResolver:
    """FKPathResolver 싱글턴"""
    global _resolver_instance
    if _resolver_instance is None:
        if schema_path is None:
            schema_path = os.path.join(
                os.path.dirname(__file__), "../../data/mes_schema.json"
            )
        _resolver_instance = FKPathResolver(schema_path)
    return _resolver_instance


if __name__ == "__main__":
    import sys

    schema = os.path.join(os.path.dirname(__file__), "../../data/mes_schema.json")
    if not os.path.exists(schema):
        schema = "data/mes_schema.json"

    resolver = FKPathResolver(schema)

    test_pairs = [
        ("CIM_LOT",            "CIM_EQUIPMENTCLASS"),   # 2홉
        ("CIM_LOT",            "CIM_PRODUCTCLASS"),      # 2홉
        ("CIM_MATERIALLOT",    "CIM_MATERIALCLASS"),     # 1홉
        ("CIM_LOT",            "CIM_PROCESSNODE"),       # 1홉
        ("CIM_PRODUCTORDER",   "CIM_PRODUCTCLASS"),      # 1홉
        ("CIM_LOT",            "CIM_FACILITY"),          # 2홉, EQUIPMENT 경유
        ("CIM_PROCESSNODE",    "CIM_PROCESSSEGMENT"),    # 1홉
        ("CIM_LOT",            "CIM_MATERIALDEFINITION"),# 연결 없음
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

    if len(sys.argv) >= 3:
        src, dst = sys.argv[1], sys.argv[2]
        print(f"\n{'='*65}")
        print(f"  사용자 입력: {src} → {dst}")
        print("="*65)
        print(resolver.describe_path(src, dst))
        for step in resolver.shortest_join_path(src, dst):
            print(f"  {step['join_clause']}")

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
