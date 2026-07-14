"""nodeskclaw-backend/tests/test_gene_lineage_migration_backfill.py

验证并查集回填逻辑本身（不依赖 alembic 运行时，直接测试同样的算法），
覆盖链式 fork、多分支 fork、孤立节点三种历史数据形状。
"""
from __future__ import annotations


def _find(parent: dict[str, str], x: str) -> str:
    root = x
    while parent[root] != root:
        root = parent[root]
    while parent[x] != root:
        parent[x], x = root, parent[x]
    return root


def _union(parent: dict[str, str], a: str, b: str) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra == rb:
        return
    if ra < rb:
        parent[rb] = ra
    else:
        parent[ra] = rb


def _compute_groups(rows: list[tuple[str, str | None]]) -> dict[str, str]:
    parent: dict[str, str] = {}
    for gene_id, parent_gene_id in rows:
        parent.setdefault(gene_id, gene_id)
        if parent_gene_id:
            parent.setdefault(parent_gene_id, parent_gene_id)
            _union(parent, gene_id, parent_gene_id)
    return {gene_id: _find(parent, gene_id) for gene_id, _ in rows}


def test_chain_fork_all_in_one_group():
    rows = [("A", None), ("B", "A"), ("C", "B")]
    groups = _compute_groups(rows)
    assert groups["A"] == groups["B"] == groups["C"]


def test_multi_branch_fork_all_in_one_group():
    rows = [("P", None), ("OrgA", "P"), ("OrgB", "P")]
    groups = _compute_groups(rows)
    assert groups["OrgA"] == groups["P"]
    assert groups["OrgB"] == groups["P"]


def test_isolated_node_gets_own_group():
    rows = [("Standalone", None)]
    groups = _compute_groups(rows)
    assert groups["Standalone"] == "Standalone"


def test_two_unrelated_lineages_stay_separate():
    rows = [("A", None), ("B", "A"), ("X", None), ("Y", "X")]
    groups = _compute_groups(rows)
    assert groups["A"] == groups["B"]
    assert groups["X"] == groups["Y"]
    assert groups["A"] != groups["X"]
