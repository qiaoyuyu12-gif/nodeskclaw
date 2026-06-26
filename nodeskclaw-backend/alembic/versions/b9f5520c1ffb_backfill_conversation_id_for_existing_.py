"""backfill_conversation_id_for_existing_messages

Revision ID: b9f5520c1ffb
Revises: 429f7d7a6e40
Create Date: 2026-04-23 20:30:14.226535

"""
from typing import Sequence, Union
from collections import defaultdict
import hashlib
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'b9f5520c1ffb'
down_revision: Union[str, Sequence[str], None] = '429f7d7a6e40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

t_workspaces = sa.table(
    "workspaces",
    sa.column("id", sa.String),
    sa.column("deleted_at", sa.DateTime),
)
t_node_cards = sa.table(
    "node_cards",
    sa.column("id", sa.String),
    sa.column("workspace_id", sa.String),
    sa.column("node_type", sa.String),
    sa.column("node_id", sa.String),
    sa.column("hex_q", sa.Integer),
    sa.column("hex_r", sa.Integer),
    sa.column("name", sa.String),
    sa.column("deleted_at", sa.DateTime),
)
t_hex_connections = sa.table(
    "hex_connections",
    sa.column("workspace_id", sa.String),
    sa.column("hex_a_q", sa.Integer),
    sa.column("hex_a_r", sa.Integer),
    sa.column("hex_b_q", sa.Integer),
    sa.column("hex_b_r", sa.Integer),
    sa.column("deleted_at", sa.DateTime),
)
t_corridor_hexes = sa.table(
    "corridor_hexes",
    sa.column("id", sa.String),
    sa.column("workspace_id", sa.String),
    sa.column("hex_q", sa.Integer),
    sa.column("hex_r", sa.Integer),
    sa.column("display_name", sa.String),
    sa.column("deleted_at", sa.DateTime),
)
t_conversations = sa.table(
    "conversations",
    sa.column("id", sa.String),
    sa.column("workspace_id", sa.String),
    sa.column("name", sa.String),
    sa.column("is_blackboard_group", sa.Boolean),
    sa.column("member_node_ids", JSONB),
    sa.column("member_hash", sa.String),
    sa.column("created_at", sa.DateTime),
    sa.column("updated_at", sa.DateTime),
)
t_workspace_messages = sa.table(
    "workspace_messages",
    sa.column("id", sa.String),
    sa.column("workspace_id", sa.String),
    sa.column("message_type", sa.String),
    sa.column("target_instance_id", sa.String),
    sa.column("conversation_id", sa.String),
)


def _compute_member_hash(member_ids: list[str]) -> str:
    joined = ",".join(sorted(member_ids))
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


def _compute_groups(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """Inline version of the 3-step grouping algorithm.

    nodes: list of {pos: (q,r), node_type: str, entity_id: str, name: str}
    edges: list of {a: (q,r), b: (q,r)}
    """
    hex_map: dict[tuple[int, int], dict] = {}
    for n in nodes:
        hex_map[n["pos"]] = n

    adj: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for e in edges:
        adj[e["a"]].append(e["b"])
        adj[e["b"]].append(e["a"])

    hub_types = {"corridor", "blackboard"}
    hub_positions = {n["pos"] for n in nodes if n["node_type"] in hub_types}
    agent_positions = {n["pos"] for n in nodes if n["node_type"] == "agent"}

    # Step 1: Hub-chain merge (Union-Find)
    parent = {p: p for p in hub_positions}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for pos in hub_positions:
        for neighbor in adj.get(pos, []):
            if neighbor in hub_positions:
                union(pos, neighbor)

    hub_chains: dict[tuple, list] = defaultdict(list)
    for pos in hub_positions:
        hub_chains[find(pos)].append(pos)

    # Step 2: Hub Group generation
    computed_groups: list[dict] = []
    agent_covered_by: dict[tuple, list[int]] = defaultdict(list)

    for _root, chain_members in hub_chains.items():
        adjacent_agents: set[tuple[int, int]] = set()
        for hub_pos in chain_members:
            for neighbor in adj.get(hub_pos, []):
                if neighbor in agent_positions:
                    adjacent_agents.add(neighbor)
            for agent_pos in agent_positions:
                if hub_pos in set(adj.get(agent_pos, [])):
                    adjacent_agents.add(agent_pos)

        if len(adjacent_agents) < 2:
            continue

        is_blackboard = any(hex_map[p]["node_type"] == "blackboard" for p in chain_members)
        member_ids = sorted(hex_map[p]["entity_id"] for p in adjacent_agents if hex_map[p].get("entity_id"))

        hub_names = [hex_map[p]["name"] for p in chain_members if hex_map[p].get("name")]
        if is_blackboard:
            name = "conversations.blackboardGroup"
        elif hub_names:
            name = hub_names[0] + "群"
        else:
            name = ", ".join(hex_map[p].get("name") or hex_map[p].get("entity_id", "?") for p in adjacent_agents)

        group_idx = len(computed_groups)
        for ap in adjacent_agents:
            agent_covered_by[ap].append(group_idx)

        computed_groups.append({
            "member_ids": member_ids,
            "is_blackboard_group": is_blackboard,
            "name": name,
        })

    # Step 3: Uncovered agent-agent edges
    uncovered_edges = []
    for agent_pos in agent_positions:
        for neighbor in adj.get(agent_pos, []):
            if neighbor not in agent_positions:
                continue
            if agent_pos >= neighbor:
                continue
            groups_a = set(agent_covered_by.get(agent_pos, []))
            groups_b = set(agent_covered_by.get(neighbor, []))
            if not (groups_a & groups_b):
                uncovered_edges.append((agent_pos, neighbor))

    if uncovered_edges:
        uf = {}
        for a, b in uncovered_edges:
            uf.setdefault(a, a)
            uf.setdefault(b, b)

        def find_uf(x):
            while uf[x] != x:
                uf[x] = uf[uf[x]]
                x = uf[x]
            return x

        def union_uf(a, b):
            ra, rb = find_uf(a), find_uf(b)
            if ra != rb:
                uf[ra] = rb

        for a, b in uncovered_edges:
            union_uf(a, b)

        components: dict[tuple, set] = defaultdict(set)
        for pos in uf:
            components[find_uf(pos)].add(pos)

        for _root, members in components.items():
            if len(members) < 2:
                continue
            member_ids = sorted(hex_map[p]["entity_id"] for p in members if hex_map[p].get("entity_id"))
            name = ", ".join(hex_map[p].get("name") or hex_map[p].get("entity_id", "?") for p in members)
            computed_groups.append({
                "member_ids": member_ids,
                "is_blackboard_group": False,
                "name": name,
            })

    return computed_groups


def upgrade() -> None:
    conn = op.get_bind()

    workspace_rows = conn.execute(
        sa.select(t_workspaces.c.id).where(
            t_workspaces.c.deleted_at.is_(None),
        )
    ).fetchall()

    for (ws_id,) in workspace_rows:
        existing_conv = conn.execute(
            sa.select(t_conversations.c.id).where(
                t_conversations.c.workspace_id == ws_id,
            ).limit(1)
        ).fetchone()
        if existing_conv:
            continue

        node_rows = conn.execute(
            sa.select(
                t_node_cards.c.node_type,
                t_node_cards.c.node_id,
                t_node_cards.c.hex_q,
                t_node_cards.c.hex_r,
                t_node_cards.c.name,
            ).where(
                t_node_cards.c.workspace_id == ws_id,
                t_node_cards.c.deleted_at.is_(None),
            )
        ).fetchall()

        corridor_rows = conn.execute(
            sa.select(
                t_corridor_hexes.c.id,
                t_corridor_hexes.c.hex_q,
                t_corridor_hexes.c.hex_r,
                t_corridor_hexes.c.display_name,
            ).where(
                t_corridor_hexes.c.workspace_id == ws_id,
                t_corridor_hexes.c.deleted_at.is_(None),
            )
        ).fetchall()

        edge_rows = conn.execute(
            sa.select(
                t_hex_connections.c.hex_a_q,
                t_hex_connections.c.hex_a_r,
                t_hex_connections.c.hex_b_q,
                t_hex_connections.c.hex_b_r,
            ).where(
                t_hex_connections.c.workspace_id == ws_id,
                t_hex_connections.c.deleted_at.is_(None),
            )
        ).fetchall()

        nodes = []
        corridor_map = {(c[1], c[2]): c[3] for c in corridor_rows}

        for ntype, nid, hq, hr, nname in node_rows:
            pos = (hq, hr)
            display = nname
            if ntype == "corridor" and pos in corridor_map:
                display = corridor_map[pos] or nname
            nodes.append({
                "pos": pos,
                "node_type": ntype,
                "entity_id": nid,
                "name": display or "",
            })

        bb_pos = (0, 0)
        if not any(n["pos"] == bb_pos and n["node_type"] == "blackboard" for n in nodes):
            nodes.append({
                "pos": bb_pos,
                "node_type": "blackboard",
                "entity_id": f"bb-{ws_id}",
                "name": "Blackboard",
            })

        edges = [{"a": (aq, ar), "b": (bq, br)} for aq, ar, bq, br in edge_rows]

        groups = _compute_groups(nodes, edges)

        if not groups:
            agent_ids = sorted(n["entity_id"] for n in nodes if n["node_type"] == "agent")
            if len(agent_ids) >= 1:
                groups = [{
                    "member_ids": agent_ids,
                    "is_blackboard_group": True,
                    "name": "conversations.blackboardGroup",
                }]

        if not groups:
            continue

        bb_conv_id = None
        conv_id_by_member: dict[str, str] = {}

        for group in groups:
            member_ids = group["member_ids"]
            if not member_ids:
                continue
            conv_id = str(uuid.uuid4())
            member_hash = _compute_member_hash(member_ids)

            conn.execute(
                t_conversations.insert().values(
                    id=conv_id,
                    workspace_id=ws_id,
                    name=group["name"],
                    is_blackboard_group=group["is_blackboard_group"],
                    member_node_ids=member_ids,
                    member_hash=member_hash,
                )
            )

            if group["is_blackboard_group"]:
                bb_conv_id = conv_id

            for mid in member_ids:
                if mid not in conv_id_by_member:
                    conv_id_by_member[mid] = conv_id

        if bb_conv_id:
            conn.execute(
                t_workspace_messages.update()
                .where(
                    t_workspace_messages.c.workspace_id == ws_id,
                    t_workspace_messages.c.message_type == "chat",
                    t_workspace_messages.c.conversation_id.is_(None),
                )
                .values(conversation_id=bb_conv_id)
            )

        collab_msgs = conn.execute(
            sa.select(
                t_workspace_messages.c.id,
                t_workspace_messages.c.target_instance_id,
            ).where(
                t_workspace_messages.c.workspace_id == ws_id,
                t_workspace_messages.c.message_type == "collaboration",
                t_workspace_messages.c.conversation_id.is_(None),
                t_workspace_messages.c.target_instance_id.isnot(None),
            )
        ).fetchall()

        for msg_id, target_iid in collab_msgs:
            target_conv = conv_id_by_member.get(target_iid)
            if not target_conv and bb_conv_id:
                target_conv = bb_conv_id
            if target_conv:
                conn.execute(
                    t_workspace_messages.update()
                    .where(t_workspace_messages.c.id == msg_id)
                    .values(conversation_id=target_conv)
                )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        t_workspace_messages.update().values(conversation_id=None)
    )
    conn.execute(
        t_conversations.delete()
    )
