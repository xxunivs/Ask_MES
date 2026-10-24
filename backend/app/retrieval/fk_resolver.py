from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from app.schema import schema_tables


@dataclass
class FKEdge:
    src_table: str
    dst_table: str
    src_col: str
    dst_col: str
    weight: int = 1

    @property
    def join_clause(self) -> str:
        return (
            f"JOIN {self.dst_table} WITH (NOLOCK) ON {self.src_table}.{self.src_col} = {self.dst_table}.{self.dst_col}"
        )

    def reversed(self) -> FKEdge:
        return FKEdge(self.dst_table, self.src_table, self.dst_col, self.src_col, self.weight)


@dataclass(order=True)
class _HeapItem:
    cost: int
    node: str
    path: list[FKEdge] = field(compare=False, default_factory=list)


class FKPathResolver:
    def __init__(self, tables: list[dict]):
        self._graph: dict[str, list[FKEdge]] = {}
        for table in tables:
            name = table["name"]
            self._graph.setdefault(name, [])
            for fk in table.get("foreign_keys", []):
                if fk["ref_table"] == name:
                    continue
                edge = FKEdge(name, fk["ref_table"], fk["column"], fk["ref_column"])
                self._graph[name].append(edge)
                self._graph.setdefault(edge.dst_table, []).append(edge.reversed())
        edges = sum(len(v) for v in self._graph.values()) // 2
        print(f"[FKResolver] 테이블 {len(self._graph)}개, FK {edges}개")

    # Dijkstra
    def shortest_join_path(self, src: str, dst: str) -> list[FKEdge]:
        if src == dst or src not in self._graph or dst not in self._graph:
            return []
        heap = [_HeapItem(0, src)]
        visited: set[str] = set()
        while heap:
            item = heapq.heappop(heap)
            if item.node in visited:
                continue
            visited.add(item.node)
            if item.node == dst:
                return item.path
            for edge in self._graph[item.node]:
                if edge.dst_table not in visited:
                    heapq.heappush(heap, _HeapItem(item.cost + edge.weight, edge.dst_table, item.path + [edge]))
        return []

    # 첫 테이블 기준 경로, 없으면 다른 테이블에서 찾음
    def get_join_sql(self, tables: list[str], max_hops: int = 4) -> str:
        clauses: list[str] = []
        anchor = tables[0] if tables else ""
        for target in dict.fromkeys(tables[1:]):
            path = self.shortest_join_path(anchor, target)
            if not path:
                path = next((p for t in tables if t != target if (p := self.shortest_join_path(t, target))), [])
            if path and len(path) <= max_hops:
                clauses += [e.join_clause for e in path if e.join_clause not in clauses]
        return "\n".join(clauses)


_resolver: FKPathResolver | None = None


def get_resolver() -> FKPathResolver:
    global _resolver
    if _resolver is None:
        _resolver = FKPathResolver(schema_tables())
    return _resolver
