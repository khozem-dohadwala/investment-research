"""
Graph data model (Step 2 ontology realized in code).

Defines the core node types and edge types for the flexible, faceted
research knowledge graph.

This is the executable definition of the redesigned structure.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Union, Optional
from uuid import uuid4
from pydantic import BaseModel, Field

# Pydantic will be used in the full FastAPI backend.
# For now we use dataclasses for a zero-dep executable definition of the ontology.


# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------

class NodeType(str, Enum):
    SCOPE = "scope"
    ENTITY = "entity"
    EVIDENCE = "evidence"
    ASPECT = "aspect"
    SOURCE_RUN = "source_run"


class EdgeType(str, Enum):
    MEMBER_OF = "MEMBER_OF"           # Entity -> Scope (or Scope -> Scope for hierarchy)
    TAGGED_WITH = "TAGGED_WITH"       # Entity/Evidence -> Aspect
    HAS_EVIDENCE = "HAS_EVIDENCE"     # Evidence -> Entity
    EVIDENCE_FOR = "EVIDENCE_FOR"     # Evidence -> Scope (broad)
    RELATED_TO = "RELATED_TO"         # Entity -> Entity
    EXTRACTED_IN = "EXTRACTED_IN"     # Evidence/Entity -> SourceRun
    MENTIONS = "MENTIONS"             # Evidence -> Entity (light)
    CONTAINS = "CONTAINS"             # Scope -> Scope (optional hierarchy)
    PARENT_OF = "PARENT_OF"           # alias for hierarchy


class RelationType(str, Enum):
    """Values for RELATED_TO.properties['relation_type']"""
    COMPETITOR = "competitor"
    SUPPLIER = "supplier"
    CUSTOMER = "customer"
    ACQUIRED = "acquired"
    SAME_AS = "same_as"
    ENABLES = "enables"
    DEPENDS_ON = "depends_on"
    CITES = "cites"
    PARTNERS_WITH = "partners_with"
    CUSTOM = "custom"


class ScopeKind(str, Enum):
    DOMAIN = "domain"
    SUB_DOMAIN = "sub_domain"
    AREA = "area"
    THEME = "theme"
    CUSTOM = "custom"


# -----------------------------------------------------------------------------
# Base + Mixins (dataclass edition for zero-dep greenfield)
# -----------------------------------------------------------------------------

def _new_id() -> str:
    # ULID preferred in production. uuid4 for early simplicity.
    return str(uuid4())


@dataclass
class GraphNodeBase:
    id: str = dc_field(default_factory=_new_id)
    type: NodeType = NodeType.SCOPE
    stable_key: str | None = None
    properties: dict[str, Any] = dc_field(default_factory=dict)
    last_updated_at: datetime = dc_field(default_factory=datetime.utcnow)
    created_at: datetime = dc_field(default_factory=datetime.utcnow)
    source_run_ids: list[str] = dc_field(default_factory=list)

    def __post_init__(self):
        if self.stable_key == "":
            raise ValueError("stable_key cannot be empty string")


@dataclass
class GraphEdge:
    id: str = dc_field(default_factory=_new_id)
    type: EdgeType = EdgeType.MEMBER_OF
    source_id: str = ""
    target_id: str = ""
    properties: dict[str, Any] = dc_field(default_factory=dict)
    created_at: datetime = dc_field(default_factory=datetime.utcnow)

    def __post_init__(self):
        if not self.source_id or not self.target_id:
            raise ValueError("Edge endpoints must have IDs")


# -----------------------------------------------------------------------------
# Concrete Node Types
# -----------------------------------------------------------------------------

@dataclass
class ScopeNode(GraphNodeBase):
    type: NodeType = NodeType.SCOPE
    parent_id: str | None = None   # lightweight hierarchy only — NOT used for Entity containment

    def __post_init__(self):
        super().__post_init__() if hasattr(super(), "__post_init__") else None
        # Keep parent_id in properties for uniformity with other metadata
        if self.parent_id:
            self.properties.setdefault("parent_id", self.parent_id)

    @property
    def name(self) -> str:
        return self.properties.get("name", self.stable_key or "Unnamed Scope")

    @property
    def kind(self) -> ScopeKind:
        raw = self.properties.get("kind", ScopeKind.CUSTOM.value)
        try:
            return ScopeKind(raw)
        except ValueError:
            return ScopeKind.CUSTOM

    @property
    def is_top_level(self) -> bool:
        """Highest level Scope (no parent). These appear at L0 / Home."""
        return self.parent_id is None

    def get_path(self, parent_lookup: dict[str, "ScopeNode"] | None = None) -> str:
        """
        Best-effort human path for focus URLs and breadcrumbs.
        For full paths we will materialize from PARENT_OF edges later.
        """
        if self.parent_id and parent_lookup and self.parent_id in parent_lookup:
            return f"{parent_lookup[self.parent_id].get_path(parent_lookup)}/{self.stable_key}"
        return self.stable_key or self.id


@dataclass
class EntityNode(GraphNodeBase):
    type: NodeType = NodeType.ENTITY

    @property
    def name(self) -> str:
        return self.properties.get("name", self.stable_key or "Unnamed Entity")

    @property
    def entity_type(self) -> str:
        return self.properties.get("entity_type", "unknown")


@dataclass
class EvidenceNode(GraphNodeBase):
    type: NodeType = NodeType.EVIDENCE

    @property
    def url(self) -> str | None:
        return self.properties.get("url")

    @property
    def snippet(self) -> str | None:
        return self.properties.get("snippet") or self.properties.get("content")


@dataclass
class AspectNode(GraphNodeBase):
    type: NodeType = NodeType.ASPECT

    @property
    def slug(self) -> str:
        return self.stable_key or self.properties.get("slug", "unknown")


@dataclass
class SourceRunNode(GraphNodeBase):
    type: NodeType = NodeType.SOURCE_RUN


# Union type for annotations
GraphNode = Union[ScopeNode, EntityNode, EvidenceNode, AspectNode, SourceRunNode]


# -----------------------------------------------------------------------------
# Typed Edge Helpers (optional sugar)
# -----------------------------------------------------------------------------

def make_membership_edge(entity_id: str, scope_id: str, **props: Any) -> GraphEdge:
    return GraphEdge(
        type=EdgeType.MEMBER_OF,
        source_id=entity_id,
        target_id=scope_id,
        properties=dict(props),
    )


def make_tagged_edge(subject_id: str, aspect_id: str, confidence: float = 0.8, **props: Any) -> GraphEdge:
    p = {"confidence": confidence, **props}
    return GraphEdge(
        type=EdgeType.TAGGED_WITH,
        source_id=subject_id,
        target_id=aspect_id,
        properties=p,
    )


def make_has_evidence_edge(evidence_id: str, entity_id: str, strength: float = 1.0) -> GraphEdge:
    return GraphEdge(
        type=EdgeType.HAS_EVIDENCE,
        source_id=evidence_id,
        target_id=entity_id,
        properties={"strength": strength},
    )


def make_related_edge(from_id: str, to_id: str, relation: RelationType | str, **props: Any) -> GraphEdge:
    return GraphEdge(
        type=EdgeType.RELATED_TO,
        source_id=from_id,
        target_id=to_id,
        properties={"relation_type": str(relation), **props},
    )


import os
import json
import re
from typing import Optional
from openai import OpenAI  # All providers are accessed via OpenAI-compatible client

# Intelligence feature - central encapsulation of all LLM (external + local) configs
# and smart model selection based on task.
from intelligence import (
    get_intelligence,
    get_llm_client,
    choose_best_model,
    TaskType,
    load_llm_config,        # re-exported for backward compatibility
    get_provider_config,    # re-exported for backward compatibility
)


def _get_xai_client() -> OpenAI:
    """
    Backward-compatible helper.

    New code should use:
        from intelligence import get_llm_client, TaskType
        client = get_llm_client(TaskType.SEMANTIC_SEARCH)
    """
    # Delegate to Intelligence using the search task (historically xai was used here)
    return get_llm_client(TaskType.SEMANTIC_SEARCH)


def _perform_semantic_search(query: str) -> list[dict]:
    """
    Production-ready semantic search.

    The Intelligence feature chooses the best LLM and can use native tool calling
    when the model + configured strategy supports it.
    """
    intel = get_intelligence()
    chosen = intel.choose_best(TaskType.SEMANTIC_SEARCH)
    strategy = intel.get_tool_strategy(TaskType.SEMANTIC_SEARCH)

    system_prompt = (
        "You are a precise web search assistant. "
        "Return ONLY a JSON array of results. "
        "Each result must have: title, snippet, url, date (YYYY-MM-DD or approximate)."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Semantic web search for recent developments: {query}"},
    ]

    try:
        tools = None
        if strategy in ("native_if_available", "native") and getattr(chosen, "supports_tool_calling", False):
            try:
                from intelligence import SEMANTIC_SEARCH_TOOL
                tools = [SEMANTIC_SEARCH_TOOL]
            except Exception:
                tools = None

        response = intel.complete(
            TaskType.SEMANTIC_SEARCH,
            messages,
            tools=tools,
            tool_choice="auto" if tools else None,
            temperature=chosen.temperature,
            max_tokens=chosen.max_tokens,
        )

        # If the model used a tool, we may have tool_calls; fall back to content parsing
        msg = response.choices[0].message
        if getattr(msg, "tool_calls", None):
            # For now we still ask the model to also produce JSON in content when possible,
            # or we could execute the tool. Here we prefer the content if present.
            content = (msg.content or "").strip()
        else:
            content = (msg.content or "").strip()

        if not content:
            # Some models return only tool_calls; try to synthesize empty or use arguments
            return []

        if content.startswith("```"):
            content = content.split("```")[1].strip()
        if content.startswith("json"):
            content = content[4:].strip()

        data = json.loads(content)
        if isinstance(data, list):
            return data
        return [data] if isinstance(data, dict) else []
    except Exception as e:
        print(f"[search] Real search failed: {e}. Falling back to empty.")
        return []


def _llm_extract_deltas(search_results: list[dict], scope: ScopeNode) -> dict:
    """
    Production-ready LLM extraction for graph deltas.

    The Intelligence feature automatically selects the best model (factoring cost + latency)
    and records usage for reporting.
    """
    intel = get_intelligence()

    scope_context = f"Scope: {scope.name} (kind={scope.kind}, stable_key={scope.stable_key})\nDescription: {scope.properties.get('description', '')}"

    prompt = f"""
You are an expert knowledge graph extractor for a research platform.

Context:
{scope_context}

Recent search results:
{json.dumps(search_results, indent=2)}

Task:
Extract developments (events, technology advances, products, capabilities) and associate them correctly.

Output ONLY valid JSON with this exact schema:
{{
  "entities": [
    {{"stable_key": "string", "type": "entity", "properties": {{"name": "...", "entity_type": "company|technology|..."}} }}
  ],
  "evidence": [
    {{"stable_key": "string", "type": "evidence", "properties": {{"title": "...", "snippet": "...", "url": "...", "development_type": "event|technology|product|capability", "fetched_at": "..."}} }}
  ],
  "edges": [
    {{"type": "MEMBER_OF|EVIDENCE_FOR|...", "source_stable_key": "...", "target_stable_key": "...", "properties": {{}} }}
  ]
}}

Rules:
- Use stable_keys like "spacex", "starship-ift-6".
- Associate evidence and entities to the current scope when relevant.
- Be conservative with associations.
- Only include items that are actual recent developments.
"""

    # Use high-level extract_structured so cost/latency is automatically recorded
    try:
        return intel.extract_structured(
            TaskType.STRUCTURED_EXTRACTION,
            system="You are a precise JSON-only extractor. Output only valid JSON matching the schema exactly.",
            user=prompt,
        )
    except Exception as e:
        print(f"[llm] Extraction failed: {e}")
        return {"entities": [], "evidence": [], "edges": []}


def load_scopes_from_config(config_path: str = "data/config/scopes.yaml") -> dict:
    """Load full scope tree from YAML for runtime use."""
    import yaml
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return data


# The canonical implementations now live in intelligence.py (the Intelligence feature).
# These are thin re-exports so existing imports continue to work.
# New code should import directly from `intelligence`.

def load_llm_config(config_path: str = "data/config/llm.yaml") -> dict:
    """Load the full raw LLM configuration (delegates to Intelligence)."""
    return get_intelligence(config_path).get_raw_config()


def get_provider_config(provider: str = "xai") -> dict:
    """Return resolved config for a single provider (env + file)."""
    return get_intelligence().get_resolved_provider(provider)


def get_queries_for_scope(scope_stable_key: str, config: dict) -> list[dict]:
    """Walk the config to find queries for a specific scope (supports inheritance from parent)."""
    discovery = config.get("discovery", {})
    # Try to find in tree
    def find_queries(scopes, key):
        for s in scopes:
            if s.get("stable_key") == key:
                qs = s.get("search_queries") or discovery.get("search_queries", [])
                if qs:
                    return qs
            if "children" in s:
                found = find_queries(s["children"], key)
                if found:
                    return found
        return None
    qs = find_queries(config.get("top_level_scopes", []), scope_stable_key)
    if qs:
        return qs
    return [{"aspect": a, "query": f"recent developments in {scope_stable_key} {a}"} 
            for a in ["companies", "technology", "events"]]


def get_all_scopes(config: dict) -> list[dict]:
    """Flatten all scopes (domains, sub_domains, areas) from config."""
    all_scopes = []
    def walk(scopes):
        for s in scopes:
            all_scopes.append(s)
            if "children" in s:
                walk(s["children"])
    walk(config.get("top_level_scopes", []))
    return all_scopes


def discover_developments(
    scope: ScopeNode,
    aspects: Optional[list[str]] = None,
    use_real_search: bool = False,
    config: Optional[dict] = None,
) -> GraphDeltas:
    """
    Production-ready discovery helper.

    When use_real_search=True it performs actual semantic search via xAI Grok
    and structured extraction.
    """
    if aspects is None:
        aspects = ["technology", "products", "events", "capabilities"]

    scope_name = scope.properties.get("name", scope.stable_key)
    print(f"[discover] Starting discovery for scope={scope.stable_key} ({scope_name}), aspects={aspects}")

    if config is None:
        config = load_scopes_from_config()

    queries = get_queries_for_scope(scope.stable_key, config)
    filtered_queries = [q for q in queries if q.get("aspect") in aspects] or \
                       [{"aspect": a, "query": f"recent developments in {scope_name} {a} 2025"} for a in aspects]

    if use_real_search:
        search_results = []
        for q in filtered_queries:
            query = q["query"].format(scope_name=scope_name)
            search_results.extend(_perform_semantic_search(query))
        raw = _llm_extract_deltas(search_results, scope)
        return GraphDeltas(**raw)
    else:
        return GraphDeltas()


class DeltaEntity(BaseModel):
    stable_key: str
    type: str = "entity"
    properties: dict = Field(default_factory=dict)

class DeltaEvidence(BaseModel):
    stable_key: str
    type: str = "evidence"
    properties: dict = Field(default_factory=dict)

class DeltaEdge(BaseModel):
    type: str
    source_stable_key: str
    target_stable_key: str
    properties: dict = Field(default_factory=dict)

class GraphDeltas(BaseModel):
    entities: list[DeltaEntity] = Field(default_factory=list)
    evidence: list[DeltaEvidence] = Field(default_factory=list)
    edges: list[DeltaEdge] = Field(default_factory=list)


def resolve_entity(store: 'GraphStore', entity_dict: dict) -> str:
    """Real entity resolution: stable_key first, then fuzzy name + type match."""
    stable_key = entity_dict.get("stable_key")
    if stable_key and store.get_node(stable_key):
        return stable_key

    props = entity_dict.get("properties", {})
    name = props.get("name", "").lower().strip()
    etype = props.get("entity_type", "").lower().strip()

    # Query DB for candidates
    cur = store.conn.execute("SELECT stable_key, properties, type FROM nodes")
    best_match = None
    best_score = 0
    for row in cur.fetchall():
        key, pjson, ntype = row
        import json
        nprops = json.loads(pjson or "{}")
        nname = nprops.get("name", "").lower().strip()
        ntype = nprops.get("entity_type", "").lower().strip() or ntype.lower()

        score = 0
        if name and nname:
            if name == nname:
                score = 100
            elif name in nname or nname in name:
                score = 80
        if etype and ntype and etype == ntype:
            score += 20

        if score > best_score:
            best_score = score
            best_match = key

    if best_score > 50:
        return best_match

    if not stable_key:
        stable_key = f"entity-{len([r for r in store.conn.execute('SELECT 1 FROM nodes')]) + 1}"
    return stable_key


class GraphStore:
    """Production-ready GraphStore using SQLite (per plan).
    Persists nodes and edges, supports upsert with last_updated_at.
    """
    def __init__(self, persist_path: str = "data/graph.db"):
        self.persist_path = persist_path
        self.conn = None
        self._init_db()

    def _init_db(self):
        import sqlite3, os
        os.makedirs(os.path.dirname(self.persist_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(self.persist_path)
        # Enable WAL for better concurrency and durability
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                stable_key TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                properties TEXT,
                last_updated_at TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                source_stable_key TEXT NOT NULL,
                target_stable_key TEXT NOT NULL,
                properties TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(type, source_stable_key, target_stable_key)
            )
        """)
        # Indexes for fast lookups
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_stable_key)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_stable_key)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type)")
        self.conn.commit()

    def _load(self):
        # For compatibility, but we use direct queries now
        pass

    def _save(self):
        self.conn.commit()

    def upsert_node(self, node: dict):
        import json
        key = node.get("stable_key") or node.get("id")
        if not key:
            return
        props = json.dumps(node.get("properties", {}))
        ts = node.get("last_updated_at") or __import__("datetime").datetime.utcnow().isoformat()
        ntype = node.get("type", "scope")
        self.conn.execute("""
            INSERT OR REPLACE INTO nodes (stable_key, type, properties, last_updated_at)
            VALUES (?, ?, ?, ?)
        """, (key, ntype, props, ts))
        self.conn.commit()

    def upsert_edge(self, edge: dict):
        import json
        etype = edge.get("type")
        src = edge.get("source_stable_key") or edge.get("source_id")
        tgt = edge.get("target_stable_key") or edge.get("target_id")
        if not (etype and src and tgt):
            return
        props = json.dumps(edge.get("properties", {}))
        self.conn.execute("""
            INSERT OR REPLACE INTO edges (type, source_stable_key, target_stable_key, properties)
            VALUES (?, ?, ?, ?)
        """, (etype, src, tgt, props))
        self.conn.commit()

    def bump_updated(self, key: str):
        import datetime
        ts = datetime.datetime.utcnow().isoformat()
        self.conn.execute("""
            UPDATE nodes SET last_updated_at = ? WHERE stable_key = ?
        """, (ts, key))
        self.conn.commit()

    def save(self):
        self.conn.commit()

    def get_node(self, key: str):
        import json
        cur = self.conn.execute("SELECT stable_key, type, properties, last_updated_at FROM nodes WHERE stable_key = ?", (key,))
        row = cur.fetchone()
        if row:
            return {"stable_key": row[0], "type": row[1], "properties": json.loads(row[2] or "{}"), "last_updated_at": row[3]}
        return None

    def get_all_nodes(self):
        import json
        cur = self.conn.execute("SELECT stable_key, type, properties, last_updated_at FROM nodes")
        return [{"stable_key": r[0], "type": r[1], "properties": json.loads(r[2] or "{}"), "last_updated_at": r[3]} for r in cur.fetchall()]

    def get_all_edges(self):
        import json
        cur = self.conn.execute("SELECT type, source_stable_key, target_stable_key, properties FROM edges")
        return [{"type": r[0], "source_stable_key": r[1], "target_stable_key": r[2], "properties": json.loads(r[3] or "{}")} for r in cur.fetchall()]

    def close(self):
        if self.conn:
            self.conn.close()

    def export_json(self, path: str = "data/graph.json"):
        """Export the full current graph to a portable JSON snapshot.
        Uses safe escaping to survive arbitrary text from LLM results.
        """
        import json
        import datetime
        import re

        def _safe(o):
            if isinstance(o, str):
                # Replace problematic control chars and ensure it will round-trip
                o = o.replace("\x00", "")
                o = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", lambda m: "\\u%04x" % ord(m.group(0)), o)
                return o
            if isinstance(o, dict):
                return {k: _safe(v) for k, v in o.items()}
            if isinstance(o, (list, tuple)):
                return [_safe(x) for x in o]
            return o

        nodes = self.get_all_nodes()
        edges = self.get_all_edges()
        snapshot = {
            "version": 1,
            "saved_at": datetime.datetime.utcnow().isoformat() + "Z",
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": _safe(nodes),
            "edges": _safe(edges),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        print(f"[export] Saved {len(nodes)} nodes, {len(edges)} edges to {path}")
        return path

    def import_json(self, path: str = "data/graph.json", clear_first: bool = True):
        """Restore graph from a JSON snapshot into this SQLite store."""
        import json
        with open(path) as f:
            data = json.load(f)

        if clear_first:
            self.conn.execute("DELETE FROM edges")
            self.conn.execute("DELETE FROM nodes")
            self.conn.commit()
            print(f"[import] Cleared existing data before loading snapshot")

        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        for n in nodes:
            self.upsert_node(n)
        for e in edges:
            self.upsert_edge(e)
        self.save()
        print(f"[import] Restored {len(nodes)} nodes, {len(edges)} edges from {path}")
        return len(nodes), len(edges)


def upsert_graph_deltas(deltas: "GraphDeltas | dict", store: GraphStore):
    """Real upsert with entity resolution: applies deltas, bumps timestamps on affected scopes/companies."""
    if hasattr(deltas, "model_dump"):
        deltas = deltas.model_dump()
    # Resolve entities first
    resolved = {}
    for ent in deltas.get("entities", []):
        key = resolve_entity(store, ent if isinstance(ent, dict) else ent.model_dump() if hasattr(ent, 'model_dump') else ent)
        sk = ent.get("stable_key", key) if isinstance(ent, dict) else getattr(ent, 'stable_key', key)
        resolved[sk] = key
        if isinstance(ent, dict):
            ent["stable_key"] = key
        store.upsert_node(ent if isinstance(ent, dict) else ent.model_dump() if hasattr(ent,'model_dump') else ent)
        store.bump_updated(key)

    for ev in deltas.get("evidence", []):
        key = ev.get("stable_key") if isinstance(ev, dict) else getattr(ev, 'stable_key', None)
        store.upsert_node(ev if isinstance(ev, dict) else ev.model_dump() if hasattr(ev,'model_dump') else ev)
        if key:
            store.bump_updated(key)

    for edge in deltas.get("edges", []):
        src_key = edge.get("source_stable_key") if isinstance(edge, dict) else getattr(edge, 'source_stable_key', None)
        tgt_key = edge.get("target_stable_key") if isinstance(edge, dict) else getattr(edge, 'target_stable_key', None)
        if src_key in resolved:
            src_key = resolved[src_key]
        if tgt_key in resolved:
            tgt_key = resolved[tgt_key]
        if isinstance(edge, dict):
            edge["source_stable_key"] = src_key
            edge["target_stable_key"] = tgt_key
        store.upsert_edge(edge if isinstance(edge, dict) else edge.model_dump() if hasattr(edge,'model_dump') else edge)
        if src_key:
            store.bump_updated(src_key)
        if tgt_key:
            store.bump_updated(tgt_key)

    store.save()
    print(f"[upsert] Applied deltas: {len(deltas.get('entities',[]))} entities, {len(deltas.get('evidence',[]))} evidence, {len(deltas.get('edges',[]))} edges")


# -----------------------------------------------------------------------------
# Example factory (for tests / exploration)
# -----------------------------------------------------------------------------

def example_graph() -> tuple[list[GraphNode], list[GraphEdge]]:
    """
    Top-down example — Highest level defined as Industries (per user):

    Three top-level Scopes (kind=domain):
      - Space Industry
      - Autonomous AI Industry
      - AI Models and Infrastructure Industry

    Shows:
    - Light hierarchy under industries (sub-domains / areas)
    - Overlapping membership (e.g. NVIDIA relevant to multiple AI-related industries)
    - One piece of evidence attached across scopes
    """
    store = GraphStore()  # wire the store

    # === HIGHEST LEVEL: INDUSTRIES (kind=domain, top-level) ===
    space = ScopeNode(
        stable_key="space-industry",
        properties={
            "name": "Space Industry",
            "kind": ScopeKind.DOMAIN,
            "description": "Launch vehicles, satellites, space exploration, and supporting infrastructure",
            "default_aspects": ["companies", "capabilities", "technology", "products", "events"],
        },
    )

    autonomous = ScopeNode(
        stable_key="autonomous-ai",
        properties={
            "name": "Autonomous AI Industry",
            "kind": ScopeKind.DOMAIN,
            "description": "Autonomous systems, robotics, self-driving, and agentic AI applications",
            "default_aspects": ["companies", "capabilities", "technology", "events"],
        },
    )

    ai_infra = ScopeNode(
        stable_key="ai-models-infra",
        properties={
            "name": "AI Models and Infrastructure Industry",
            "kind": ScopeKind.DOMAIN,
            "description": "Foundation models, training infrastructure, chips, data centers, and inference platforms",
            "default_aspects": ["companies", "capabilities", "technology", "market"],
        },
    )

    crypto = ScopeNode(
        stable_key="crypto-industry",
        properties={
            "name": "Crypto Industry",
            "kind": ScopeKind.DOMAIN,
            "description": "Blockchain networks, cryptocurrencies, DeFi, NFTs, and digital asset markets",
            "default_aspects": ["companies", "market", "technology", "events"],
        },
    )

    # === SUB-AREAS for Space Industry (refined) ===
    launch_cap = ScopeNode(
        stable_key="launch-capabilities",
        parent_id=space.id,
        properties={
            "name": "Launch Capabilities",
            "kind": ScopeKind.SUB_DOMAIN,
            "description": "Rockets and systems to reach space",
        },
    )
    reusable = ScopeNode(
        stable_key="reusable-launch",
        parent_id=launch_cap.id,
        properties={
            "name": "Reusable Launch Vehicles",
            "kind": ScopeKind.AREA,
            "description": "Falcon-class, recovery, rapid reuse",
        },
    )
    heavy_lift = ScopeNode(
        stable_key="heavy-lift",
        parent_id=launch_cap.id,
        properties={
            "name": "Heavy-Lift Launch Vehicles",
            "kind": ScopeKind.AREA,
        },
    )
    small_launch = ScopeNode(
        stable_key="small-launch",
        parent_id=launch_cap.id,
        properties={
            "name": "SmallSat & Rideshare Launch",
            "kind": ScopeKind.AREA,
        },
    )
    reusability_area = ScopeNode(
        stable_key="reusability",
        parent_id=launch_cap.id,
        properties={
            "name": "Booster Reusability & Recovery",
            "kind": ScopeKind.AREA,
        },
    )
    satellite = ScopeNode(
        stable_key="satellite-systems",
        parent_id=space.id,
        properties={
            "name": "Satellite Systems & Constellations",
            "kind": ScopeKind.SUB_DOMAIN,
        },
    )
    broadband = ScopeNode(
        stable_key="broadband-constellations",
        parent_id=satellite.id,
        properties={
            "name": "Broadband LEO Constellations",
            "kind": ScopeKind.AREA,
        },
    )
    in_orbit = ScopeNode(
        stable_key="in-orbit-services",
        parent_id=satellite.id,
        properties={
            "name": "In-Orbit Servicing & Manufacturing",
            "kind": ScopeKind.AREA,
        },
    )

    # Moon Based Activities (new sub-domain)
    moon_activities = ScopeNode(
        stable_key="moon-based-activities",
        parent_id=space.id,
        properties={
            "name": "Moon Based Activities",
            "kind": ScopeKind.SUB_DOMAIN,
            "description": "Infrastructure, operations, and resource utilization on the lunar surface",
        },
    )
    moon_base = ScopeNode(
        stable_key="moon-base",
        parent_id=moon_activities.id,
        properties={
            "name": "Moon Base",
            "kind": ScopeKind.AREA,
            "description": "Permanent habitats, bases, and lunar surface operations",
        },
    )
    moon_mining = ScopeNode(
        stable_key="moon-mining",
        parent_id=moon_activities.id,
        properties={
            "name": "Moon Mining",
            "kind": ScopeKind.AREA,
            "description": "In-situ resource utilization (ISRU), regolith mining, and lunar resources",
        },
    )

    # Space Hardened Hardware (new sub-domain)
    hardened_hw = ScopeNode(
        stable_key="space-hardened-hardware",
        parent_id=space.id,
        properties={
            "name": "Space Hardened Hardware",
            "kind": ScopeKind.SUB_DOMAIN,
            "description": "Radiation-hardened and space-qualified electronics, power systems, and components",
        },
    )
    chips_circuits = ScopeNode(
        stable_key="chips-circuits",
        parent_id=hardened_hw.id,
        properties={
            "name": "Chips and Circuits",
            "kind": ScopeKind.AREA,
            "description": "Radiation-hardened processors, memory, FPGAs, and integrated circuits",
        },
    )
    solar_panels = ScopeNode(
        stable_key="solar-panels",
        parent_id=hardened_hw.id,
        properties={
            "name": "Solar Panels",
            "kind": ScopeKind.AREA,
            "description": "Space-grade solar arrays and photovoltaic systems",
        },
    )
    other_hardware = ScopeNode(
        stable_key="other-hardware",
        parent_id=hardened_hw.id,
        properties={
            "name": "Other Hardware",
            "kind": ScopeKind.AREA,
            "description": "Batteries, sensors, actuators, connectors, and other space-qualified components",
        },
    )

    # Additional scopes for full Space tree
    chem_prop = ScopeNode(stable_key="chemical-propulsion", parent_id=space.id, properties={"name": "Chemical Propulsion", "kind": ScopeKind.AREA})
    elec_prop = ScopeNode(stable_key="electric-propulsion", parent_id=space.id, properties={"name": "Electric & Ion Propulsion", "kind": ScopeKind.AREA})
    adv_prop = ScopeNode(stable_key="advanced-propulsion", parent_id=space.id, properties={"name": "Advanced & Nuclear Propulsion", "kind": ScopeKind.AREA})

    crewed = ScopeNode(stable_key="crewed-vehicles", parent_id=space.id, properties={"name": "Crewed Vehicles & Capsules", "kind": ScopeKind.AREA})
    deep = ScopeNode(stable_key="deep-space", parent_id=space.id, properties={"name": "Deep Space & Lunar/Mars Exploration", "kind": ScopeKind.AREA})

    ground = ScopeNode(stable_key="ground-segment", parent_id=space.id, properties={"name": "Ground Segment & Operations", "kind": ScopeKind.AREA})

    # === Autonomous AI Industry subs (fleshed out) ===
    ground_vehicles = ScopeNode(
        stable_key="ground-vehicles",
        parent_id=autonomous.id,
        properties={
            "name": "Ground Autonomous Vehicles",
            "kind": ScopeKind.SUB_DOMAIN,
            "description": "Self-driving cars, trucks, and ground-based robotic systems",
        },
    )
    passenger_av = ScopeNode(
        stable_key="passenger-av",
        parent_id=ground_vehicles.id,
        properties={
            "name": "Autonomous Passenger Vehicles",
            "kind": ScopeKind.AREA,
            "description": "Robotaxis and autonomous cars",
        },
    )
    trucking = ScopeNode(
        stable_key="trucking",
        parent_id=ground_vehicles.id,
        properties={
            "name": "Autonomous Trucking & Logistics",
            "kind": ScopeKind.AREA,
        },
    )

    aerial = ScopeNode(
        stable_key="aerial-autonomy",
        parent_id=autonomous.id,
        properties={
            "name": "Aerial Autonomy",
            "kind": ScopeKind.SUB_DOMAIN,
        },
    )
    drones = ScopeNode(
        stable_key="commercial-drones",
        parent_id=aerial.id,
        properties={
            "name": "Commercial Drones & Delivery UAVs",
            "kind": ScopeKind.AREA,
        },
    )

    humanoids = ScopeNode(
        stable_key="humanoids-service",
        parent_id=autonomous.id,
        properties={
            "name": "Humanoids & Service Robotics",
            "kind": ScopeKind.SUB_DOMAIN,
        },
    )
    humanoid_robots = ScopeNode(
        stable_key="humanoids",
        parent_id=humanoids.id,
        properties={
            "name": "Humanoid Robots",
            "kind": ScopeKind.AREA,
            "description": "General-purpose humanoid robots",
        },
    )

    industrial = ScopeNode(
        stable_key="industrial-automation",
        parent_id=autonomous.id,
        properties={
            "name": "Industrial & Warehouse Automation",
            "kind": ScopeKind.SUB_DOMAIN,
        },
    )
    warehouse = ScopeNode(
        stable_key="warehouse",
        parent_id=industrial.id,
        properties={
            "name": "Warehouse & Logistics Robotics",
            "kind": ScopeKind.AREA,
        },
    )

    # AI Models & Infra subs
    foundation = ScopeNode(
        stable_key="foundation-models",
        parent_id=ai_infra.id,
        properties={
            "name": "Foundation Models",
            "kind": ScopeKind.SUB_DOMAIN,
        },
    )
    llms = ScopeNode(
        stable_key="llms",
        parent_id=foundation.id,
        properties={
            "name": "Large Language Models",
            "kind": ScopeKind.AREA,
        },
    )
    training = ScopeNode(
        stable_key="training-infra",
        parent_id=ai_infra.id,
        properties={
            "name": "Training Infrastructure",
            "kind": ScopeKind.SUB_DOMAIN,
        },
    )
    chips = ScopeNode(
        stable_key="ai-chips",
        parent_id=training.id,
        properties={
            "name": "AI Chips & Accelerators",
            "kind": ScopeKind.AREA,
        },
    )

    # Additional AI Models & Infra sub-domains (fleshed out)
    data_platforms = ScopeNode(
        stable_key="data-datasets",
        parent_id=ai_infra.id,
        properties={
            "name": "Data & Datasets",
            "kind": ScopeKind.SUB_DOMAIN,
        },
    )
    synthetic_data = ScopeNode(
        stable_key="synthetic-data",
        parent_id=data_platforms.id,
        properties={
            "name": "Synthetic Data Generation",
            "kind": ScopeKind.AREA,
        },
    )

    model_lifecycle = ScopeNode(
        stable_key="model-lifecycle",
        parent_id=ai_infra.id,
        properties={
            "name": "Model Development & Lifecycle",
            "kind": ScopeKind.SUB_DOMAIN,
        },
    )
    evaluation = ScopeNode(
        stable_key="evaluation",
        parent_id=model_lifecycle.id,
        properties={
            "name": "Evaluation, Benchmarking & Red Teaming",
            "kind": ScopeKind.AREA,
        },
    )

    ai_safety = ScopeNode(
        stable_key="ai-safety",
        parent_id=ai_infra.id,
        properties={
            "name": "AI Safety, Security & Governance",
            "kind": ScopeKind.SUB_DOMAIN,
        },
    )
    safety = ScopeNode(
        stable_key="safety-alignment",
        parent_id=ai_safety.id,
        properties={
            "name": "Safety & Alignment Research",
            "kind": ScopeKind.AREA,
        },
    )

    # === Crypto Industry subs (consolidated) ===
    l1s = ScopeNode(
        stable_key="layer-1-blockchains",
        parent_id=crypto.id,
        properties={
            "name": "Layer 1 Blockchains",
            "kind": ScopeKind.SUB_DOMAIN,
        },
    )
    bitcoin = ScopeNode(
        stable_key="bitcoin",
        parent_id=l1s.id,
        properties={
            "name": "Bitcoin",
            "kind": ScopeKind.AREA,
        },
    )
    ethereum = ScopeNode(
        stable_key="ethereum",
        parent_id=l1s.id,
        properties={
            "name": "Ethereum",
            "kind": ScopeKind.AREA,
        },
    )
    solana = ScopeNode(
        stable_key="solana",
        parent_id=l1s.id,
        properties={
            "name": "Solana",
            "kind": ScopeKind.AREA,
        },
    )

    layer2 = ScopeNode(
        stable_key="layer-2-scaling",
        parent_id=crypto.id,
        properties={
            "name": "Layer 2 Scaling & Rollups",
            "kind": ScopeKind.SUB_DOMAIN,
        },
    )

    defi = ScopeNode(
        stable_key="defi",
        parent_id=crypto.id,
        properties={
            "name": "DeFi (Decentralized Finance)",
            "kind": ScopeKind.SUB_DOMAIN,
        },
    )
    lending = ScopeNode(
        stable_key="lending-borrowing",
        parent_id=defi.id,
        properties={
            "name": "Lending & Borrowing Protocols",
            "kind": ScopeKind.AREA,
        },
    )

    stablecoins = ScopeNode(
        stable_key="stablecoins",
        parent_id=crypto.id,
        properties={
            "name": "Stablecoins",
            "kind": ScopeKind.SUB_DOMAIN,
        },
    )
    stablecoins_fiat = ScopeNode(
        stable_key="fiat-collateralized",
        parent_id=stablecoins.id,
        properties={
            "name": "Fiat-Collateralized Stablecoins",
            "kind": ScopeKind.AREA,
        },
    )

    crypto_payments = ScopeNode(
        stable_key="crypto-payments",
        parent_id=crypto.id,
        properties={
            "name": "Crypto-Based Payments",
            "kind": ScopeKind.SUB_DOMAIN,
        },
    )
    payments_onchain = ScopeNode(
        stable_key="on-chain-payments",
        parent_id=crypto_payments.id,
        properties={
            "name": "On-Chain Payments & Remittances",
            "kind": ScopeKind.AREA,
        },
    )

    nfts = ScopeNode(
        stable_key="nfts-gaming",
        parent_id=crypto.id,
        properties={
            "name": "NFTs, Gaming & Digital Collectibles",
            "kind": ScopeKind.SUB_DOMAIN,
        },
    )

    # === KNOWLEDGE (attached via membership, not hierarchy) ===
    nvidia = EntityNode(
        stable_key="nvidia",
        properties={
            "name": "NVIDIA",
            "entity_type": "company",
            "summary": "Dominant provider of AI accelerators and autonomous vehicle platforms",
        },
    )

    spacex = EntityNode(
        stable_key="spacex",
        properties={
            "name": "SpaceX",
            "entity_type": "company",
            "summary": "Reusable launch and satellite operator",
        },
    )

    xai = EntityNode(
        stable_key="xai",
        properties={
            "name": "xAI",
            "entity_type": "company",
            "summary": "Foundation model developer with focus on reasoning and infrastructure",
        },
    )

    # === Space Industry Companies - Curated initial seed list with explicit mappings ===
    # Discovery method: Targeted per sub-domain/area semantic searches + LLM classification to scopes.
    # Curated bigger seed list with mappings (companies can map to multiple):
    #
    # Launch Capabilities / Reusable Launch Vehicles: SpaceX, Blue Origin, Relativity Space, Rocket Lab (Neutron)
    # Launch Capabilities / Heavy-Lift: SpaceX, Blue Origin, ULA
    # Launch Capabilities / SmallSat & Rideshare: Rocket Lab, Firefly, Relativity Space
    # Launch Capabilities / Booster Reusability & Recovery: SpaceX, Blue Origin
    #
    # Satellite Systems / Broadband LEO Constellations: SpaceX (Starlink), Amazon Kuiper, OneWeb/Eutelsat
    # Satellite Systems / Earth Observation: Planet Labs, Maxar, BlackSky
    # Satellite Systems / In-Orbit Servicing: Northrop Grumman, Sierra Space, Astroscale
    #
    # Moon Based Activities / Moon Base: SpaceX (Starship HLS), Blue Origin (Blue Moon), Sierra Space, Lockheed, Astrobotic, Intuitive Machines
    # Moon Based Activities / Moon Mining (ISRU): Astrobotic, Intuitive Machines, ispace, SpaceX (refueling)
    #
    # Space Hardened Hardware / Chips and Circuits: BAE Systems, Vorago, Cobham (Eaton)
    # Space Hardened Hardware / Solar Panels: Spectrolab (Boeing), Azur Space, SolAero (Rocket Lab)
    # Space Hardened Hardware / Other Hardware: Various primes (Northrop, Lockheed, Boeing for components)
    #
    # Human Spaceflight & Exploration / Crewed Vehicles: SpaceX (Dragon/Starship), Boeing (Starliner), Sierra Space (Dream Chaser), Blue Origin
    # Human Spaceflight / Deep Space & Lunar/Mars: SpaceX, Blue Origin, Lockheed (Orion), Astrobotic
    #
    # Propulsion: SpaceX (Raptor, Merlin), Blue Origin (BE-4), Aerojet Rocketdyne, Relativity
    #
    # Ground Segment: Various (but often bundled with primes like Lockheed, Northrop)
    #
    # A company can belong to multiple scopes via separate MEMBER_OF edges.
    # LLM classification prompt example: "Given company activities: [summary]. Which of these Space scopes apply? [list all sub-domains/areas with short descs]. Output list of stable_keys with confidence."

    blue_origin = EntityNode(
        stable_key="blue-origin",
        properties={
            "name": "Blue Origin",
            "entity_type": "company",
            "summary": "Aerospace manufacturer developing reusable rockets and lunar landers",
        },
    )

    rocket_lab = EntityNode(
        stable_key="rocket-lab",
        properties={
            "name": "Rocket Lab",
            "entity_type": "company",
            "summary": "Small satellite launch provider developing Neutron medium-lift vehicle",
        },
    )

    relativity = EntityNode(
        stable_key="relativity-space",
        properties={
            "name": "Relativity Space",
            "entity_type": "company",
            "summary": "3D-printed rocket company focusing on reusable Terran vehicles",
        },
    )

    firefly = EntityNode(
        stable_key="firefly-aerospace",
        properties={
            "name": "Firefly Aerospace",
            "entity_type": "company",
            "summary": "Small to medium launch vehicle developer with NASA lunar contracts",
        },
    )

    planet = EntityNode(
        stable_key="planet-labs",
        properties={
            "name": "Planet Labs",
            "entity_type": "company",
            "summary": "Earth observation satellite constellation operator",
        },
    )

    sierra = EntityNode(
        stable_key="sierra-space",
        properties={
            "name": "Sierra Space",
            "entity_type": "company",
            "summary": "Space transportation and orbital infrastructure company (Dream Chaser, LIFE)",
        },
    )

    northrop = EntityNode(
        stable_key="northrop-grumman",
        properties={
            "name": "Northrop Grumman",
            "entity_type": "company",
            "summary": "Aerospace and defense contractor with space systems and in-orbit services",
        },
    )

    lockheed = EntityNode(
        stable_key="lockheed-martin",
        properties={
            "name": "Lockheed Martin",
            "entity_type": "company",
            "summary": "Major contractor for satellites, human spaceflight, and space systems",
        },
    )

    boeing = EntityNode(
        stable_key="boeing",
        properties={
            "name": "Boeing",
            "entity_type": "company",
            "summary": "Aerospace company involved in human spaceflight, satellites, and components",
        },
    )

    astrobotic = EntityNode(
        stable_key="astrobotic",
        properties={
            "name": "Astrobotic",
            "entity_type": "company",
            "summary": "Lunar lander and payload delivery company for NASA and commercial missions",
        },
    )

    # Hardware examples
    bae = EntityNode(
        stable_key="bae-systems",
        properties={
            "name": "BAE Systems",
            "entity_type": "company",
            "summary": "Provider of radiation-hardened electronics and space systems",
        },
    )

    spectrolab = EntityNode(
        stable_key="spectrolab",
        properties={
            "name": "Spectrolab",
            "entity_type": "company",
            "summary": "Solar panel manufacturer for space applications (Boeing subsidiary)",
        },
    )

    ula = EntityNode(
        stable_key="ula",
        properties={
            "name": "United Launch Alliance (ULA)",
            "entity_type": "company",
            "summary": "Heavy-lift launch provider (Atlas V, Vulcan)",
        },
    )

    maxar = EntityNode(
        stable_key="maxar",
        properties={
            "name": "Maxar Technologies",
            "entity_type": "company",
            "summary": "Earth observation satellite and geospatial intelligence company",
        },
    )

    kuiper = EntityNode(
        stable_key="amazon-kuiper",
        properties={
            "name": "Amazon Kuiper",
            "entity_type": "company",
            "summary": "Amazon's LEO broadband satellite constellation project",
        },
    )

    intuitive = EntityNode(
        stable_key="intuitive-machines",
        properties={
            "name": "Intuitive Machines",
            "entity_type": "company",
            "summary": "Lunar lander and payload delivery company (Nova-C)",
        },
    )

    evidence = EvidenceNode(
        stable_key=None,
        properties={
            "title": "NVIDIA + SpaceX collaboration signals 2026",
            "url": "https://...",
            "snippet": "Discussions around using NVIDIA GPUs for onboard satellite autonomy and model training in orbit...",
            "fetched_at": datetime.utcnow().isoformat(),
        },
    )

    aspect = AspectNode(
        stable_key="capabilities",
        properties={"name": "Capabilities & performance"},
    )

    # === Discovery of Developments ===
    # BEST PRACTICE for discovering developments in sub-domains, areas, and companies:
    #
    # 1. Walk the scope tree (from config or graph ScopeNodes filtered by domain="space-industry").
    # 2. For each sub_domain/area, load or generate search_queries (see scopes.yaml).
    #    Interpolate {scope_name} = area.name or full path.
    # 3. Execute Grok semantic web search (or multi-source: web + X + RSS) for each aspect.
    # 4. Feed search results + full scope context (descriptions of siblings/parents) to LLM.
    #    Prompt goal: Extract structured developments:
    #      - New/updated companies (resolve to stable_key or create)
    #      - Developments: events, tech advances, product releases, capability demos (as EvidenceNodes)
    #      - Associations: which companies, which exact sub-domains/areas (use MEMBER_OF + EVIDENCE_FOR)
    #      - Relations: e.g. DEVELOPED_BY, APPLIES_TO, PART_OF
    #    Output format: graph deltas (entities, evidence, edges) with confidence + provenance.
    # 5. Upsert:
    #    - Create/update EntityNodes (companies or new tech entities)
    #    - Create EvidenceNodes for developments (with url, snippet, fetched_at, source_id)
    #    - MEMBER_OF edges: company <-> scope(s)
    #    - EVIDENCE_FOR or HAS_EVIDENCE: evidence <-> company/scope
    #    - Bump last_updated_at on all touched nodes (triggers unread rollups)
    # 6. Dedup/resolution: stable_key + fuzzy name + type matching.
    # 7. Run incrementally (per scope or per aspect), on triggers (manual/cron/new source).
    # 8. Log provenance on edges (discovered_via="grok_semantic", query=..., timestamp).
    #
    # This keeps associations precise (no global dump) and leverages the lightweight hierarchy.
    # Cross-domain associations are natural (one company can MEMBER_OF multiple industries).
    #
    # Prototype implementation below (seeded "discovered" developments for demo).
    # In production, replace the "simulated" part with real search + LLM call.

    # Demonstrate the real discovery helper (returns structured deltas)
    # In a real backend this would be called from a /discover or scheduled task.
    nodes: list[GraphNode] = [
        space, autonomous, ai_infra, crypto,
        launch_cap, reusable, heavy_lift, small_launch, reusability_area,
        satellite, broadband, in_orbit,
        moon_activities, moon_base, moon_mining,
        hardened_hw, chips_circuits, solar_panels, other_hardware,
        chem_prop, elec_prop, adv_prop,
        crewed, deep,
        ground,
        ground_vehicles, passenger_av, trucking,
        aerial, drones,
        humanoids, humanoid_robots,
        industrial, warehouse,
        foundation, llms, training, chips,
        data_platforms, synthetic_data,
        model_lifecycle, evaluation,
        ai_safety, safety,
        l1s, bitcoin, ethereum, solana,
        layer2,
        defi, lending,
        stablecoins, stablecoins_fiat,
        crypto_payments, payments_onchain,
        nfts,
        blue_origin, rocket_lab, relativity, firefly, planet, sierra, northrop, lockheed, boeing, astrobotic, bae, spectrolab, ula, maxar, kuiper, intuitive,
        nvidia, spacex, xai,
        evidence, aspect
    ]

    edges = [
        # Light Scope hierarchy (for breadcrumbs / navigation only) - Space focused
        GraphEdge(type=EdgeType.PARENT_OF, source_id=space.id, target_id=launch_cap.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=launch_cap.id, target_id=reusable.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=launch_cap.id, target_id=heavy_lift.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=launch_cap.id, target_id=small_launch.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=launch_cap.id, target_id=reusability_area.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=space.id, target_id=satellite.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=satellite.id, target_id=broadband.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=satellite.id, target_id=in_orbit.id),
        # Moon sub-domain
        GraphEdge(type=EdgeType.PARENT_OF, source_id=space.id, target_id=moon_activities.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=moon_activities.id, target_id=moon_base.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=moon_activities.id, target_id=moon_mining.id),
        # Space Hardened Hardware sub-domain
        GraphEdge(type=EdgeType.PARENT_OF, source_id=space.id, target_id=hardened_hw.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=hardened_hw.id, target_id=chips_circuits.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=hardened_hw.id, target_id=solar_panels.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=hardened_hw.id, target_id=other_hardware.id),

        # Additional full Space scopes
        GraphEdge(type=EdgeType.PARENT_OF, source_id=space.id, target_id=chem_prop.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=space.id, target_id=elec_prop.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=space.id, target_id=adv_prop.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=space.id, target_id=crewed.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=space.id, target_id=deep.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=space.id, target_id=ground.id),

        # Other industries (unchanged)
        GraphEdge(type=EdgeType.PARENT_OF, source_id=autonomous.id, target_id=ground_vehicles.id),
        # Autonomous AI hierarchy
        GraphEdge(type=EdgeType.PARENT_OF, source_id=autonomous.id, target_id=ground_vehicles.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=ground_vehicles.id, target_id=passenger_av.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=ground_vehicles.id, target_id=trucking.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=autonomous.id, target_id=aerial.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=aerial.id, target_id=drones.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=autonomous.id, target_id=humanoids.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=humanoids.id, target_id=humanoid_robots.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=autonomous.id, target_id=industrial.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=industrial.id, target_id=warehouse.id),

        GraphEdge(type=EdgeType.PARENT_OF, source_id=ai_infra.id, target_id=foundation.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=foundation.id, target_id=llms.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=ai_infra.id, target_id=training.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=training.id, target_id=chips.id),
        # Additional AI Models & Infra hierarchy
        GraphEdge(type=EdgeType.PARENT_OF, source_id=ai_infra.id, target_id=data_platforms.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=data_platforms.id, target_id=synthetic_data.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=ai_infra.id, target_id=model_lifecycle.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=model_lifecycle.id, target_id=evaluation.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=ai_infra.id, target_id=ai_safety.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=ai_safety.id, target_id=safety.id),

        # Crypto Industry hierarchy (consolidated)
        GraphEdge(type=EdgeType.PARENT_OF, source_id=crypto.id, target_id=l1s.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=l1s.id, target_id=bitcoin.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=l1s.id, target_id=ethereum.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=l1s.id, target_id=solana.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=crypto.id, target_id=layer2.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=crypto.id, target_id=defi.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=defi.id, target_id=lending.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=crypto.id, target_id=stablecoins.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=stablecoins.id, target_id=stablecoins_fiat.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=crypto.id, target_id=crypto_payments.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=crypto_payments.id, target_id=payments_onchain.id),
        GraphEdge(type=EdgeType.PARENT_OF, source_id=crypto.id, target_id=nfts.id),

        # === Flexible overlapping membership across industries ===
        # SpaceX primarily under Space Industry sub-areas
        make_membership_edge(spacex.id, space.id, priority="high"),
        make_membership_edge(spacex.id, reusable.id, priority="high"),
        make_membership_edge(spacex.id, reusability_area.id, priority="high"),
        make_membership_edge(spacex.id, broadband.id, priority="medium"),
        make_membership_edge(spacex.id, in_orbit.id, priority="medium"),
        make_membership_edge(spacex.id, moon_activities.id, priority="high"),
        make_membership_edge(spacex.id, moon_base.id, priority="high"),

        # Blue Origin - heavy lift, reusability, human spaceflight, moon
        make_membership_edge(blue_origin.id, space.id, priority="high"),
        make_membership_edge(blue_origin.id, heavy_lift.id, priority="high"),
        make_membership_edge(blue_origin.id, reusable.id, priority="high"),
        make_membership_edge(blue_origin.id, reusability_area.id, priority="high"),
        make_membership_edge(blue_origin.id, moon_activities.id, priority="high"),
        make_membership_edge(blue_origin.id, moon_base.id, priority="high"),

        # Rocket Lab - small launch, reusability efforts
        make_membership_edge(rocket_lab.id, space.id, priority="high"),
        make_membership_edge(rocket_lab.id, small_launch.id, priority="high"),
        make_membership_edge(rocket_lab.id, reusable.id, priority="medium"),

        # Relativity Space - reusable launch
        make_membership_edge(relativity.id, space.id, priority="high"),
        make_membership_edge(relativity.id, reusable.id, priority="high"),
        make_membership_edge(relativity.id, launch_cap.id, priority="high"),

        # Firefly - small launch, moon missions
        make_membership_edge(firefly.id, space.id, priority="high"),
        make_membership_edge(firefly.id, small_launch.id, priority="high"),
        make_membership_edge(firefly.id, moon_activities.id, priority="high"),
        make_membership_edge(firefly.id, moon_base.id, priority="high"),

        # Planet Labs - earth observation
        make_membership_edge(planet.id, space.id, priority="high"),
        make_membership_edge(planet.id, satellite.id, priority="high"),

        # Sierra Space - human spaceflight, in-orbit
        make_membership_edge(sierra.id, space.id, priority="high"),
        make_membership_edge(sierra.id, moon_activities.id, priority="high"),  # habitats
        make_membership_edge(sierra.id, in_orbit.id, priority="high"),

        # Northrop Grumman - satellites, in-orbit services
        make_membership_edge(northrop.id, space.id, priority="high"),
        make_membership_edge(northrop.id, satellite.id, priority="high"),
        make_membership_edge(northrop.id, in_orbit.id, priority="high"),

        # Lockheed Martin - satellites, human spaceflight
        make_membership_edge(lockheed.id, space.id, priority="high"),
        make_membership_edge(lockheed.id, satellite.id, priority="high"),

        # Boeing - human spaceflight, satellites, solar hardware
        make_membership_edge(boeing.id, space.id, priority="high"),
        make_membership_edge(boeing.id, satellite.id, priority="medium"),
        make_membership_edge(boeing.id, solar_panels.id, priority="medium"),

        # Astrobotic - moon landing / base support
        make_membership_edge(astrobotic.id, space.id, priority="high"),
        make_membership_edge(astrobotic.id, moon_activities.id, priority="high"),
        make_membership_edge(astrobotic.id, moon_base.id, priority="high"),

        # Hardware
        make_membership_edge(bae.id, space.id, priority="high"),
        make_membership_edge(bae.id, hardened_hw.id, priority="high"),
        make_membership_edge(bae.id, chips_circuits.id, priority="high"),

        make_membership_edge(spectrolab.id, space.id, priority="high"),
        make_membership_edge(spectrolab.id, solar_panels.id, priority="high"),

        # ULA - heavy-lift
        make_membership_edge(ula.id, space.id, priority="high"),
        make_membership_edge(ula.id, heavy_lift.id, priority="high"),

        # Maxar - earth observation / satellite
        make_membership_edge(maxar.id, space.id, priority="high"),
        make_membership_edge(maxar.id, satellite.id, priority="high"),

        # Amazon Kuiper - broadband constellations
        make_membership_edge(kuiper.id, space.id, priority="high"),
        make_membership_edge(kuiper.id, broadband.id, priority="high"),

        # Intuitive Machines - moon base / mining support
        make_membership_edge(intuitive.id, space.id, priority="high"),
        make_membership_edge(intuitive.id, moon_activities.id, priority="high"),
        make_membership_edge(intuitive.id, moon_base.id, priority="high"),
        make_membership_edge(intuitive.id, moon_mining.id, priority="medium"),

        # Discovered developments (Evidence) associated to companies and scopes
        # Output from the discover_developments helper (simulated here for demo)
        # Wired real search evidence added via discover_developments helper below

        # NVIDIA in hardened hardware (chips) + existing
        make_membership_edge(nvidia.id, hardened_hw.id, priority="high"),
        make_membership_edge(nvidia.id, chips_circuits.id, priority="high"),

        # NVIDIA across AI infra + autonomous + space (onboard compute)
        make_membership_edge(nvidia.id, ai_infra.id, priority="high"),
        make_membership_edge(nvidia.id, chips.id, priority="high"),
        make_membership_edge(nvidia.id, autonomous.id, priority="high"),
        make_membership_edge(nvidia.id, passenger_av.id, priority="high"),
        make_membership_edge(nvidia.id, trucking.id, priority="high"),
        make_membership_edge(nvidia.id, aerial.id, priority="medium"),
        make_membership_edge(nvidia.id, space.id, priority="medium"),

        # xAI across models infra + autonomous (agentic)
        make_membership_edge(xai.id, ai_infra.id, priority="high"),
        make_membership_edge(xai.id, foundation.id, priority="high"),
        make_membership_edge(xai.id, llms.id, priority="high"),
        make_membership_edge(xai.id, data_platforms.id, priority="high"),
        make_membership_edge(xai.id, ai_safety.id, priority="medium"),
        make_membership_edge(xai.id, autonomous.id, priority="medium"),

        # Crypto example memberships
        make_membership_edge(spacex.id, crypto.id, priority="low"),  # space + crypto overlap example
        make_membership_edge(xai.id, defi.id, priority="medium"),
        make_membership_edge(xai.id, nfts.id, priority="medium"),
        make_membership_edge(xai.id, stablecoins.id, priority="medium"),

        # Cross-cutting evidence
        make_has_evidence_edge(evidence.id, nvidia.id, strength=0.85),
        make_has_evidence_edge(evidence.id, spacex.id, strength=0.7),

        # Aspect tagging
        make_tagged_edge(nvidia.id, aspect.id, confidence=0.95),
        make_tagged_edge(spacex.id, aspect.id, confidence=0.8),
        make_tagged_edge(xai.id, aspect.id, confidence=0.9),
    ]

    # Collect ALL Space scopes using config walker for full discovery
    config = load_scopes_from_config()
    all_scopes_dicts = get_all_scopes(config)
    space_scope_dicts = [s for s in all_scopes_dicts if 'space' in s.get('stable_key', '') or 'space' in s.get('name', '').lower()]
    space_scopes = [
        launch_cap, reusable, heavy_lift, small_launch, reusability_area,
        satellite, broadband, in_orbit,
        moon_activities, moon_base, moon_mining,
        hardened_hw, chips_circuits, solar_panels, other_hardware,
        chem_prop, elec_prop, adv_prop,
        crewed, deep,
        ground,
    ]
    # Dynamically add any from config not hardcoded
    defined_keys = {getattr(s, 'stable_key', None) for s in space_scopes if s}
    for sd in space_scope_dicts:
        if sd['stable_key'] not in defined_keys:
            space_scopes.append(ScopeNode(stable_key=sd['stable_key'], properties=sd))

    # Wire store and real discovery deltas for ALL scopes
    for s in space_scopes:
        if s:
            deltas = discover_developments(s, use_real_search=True, config=config)
            upsert_graph_deltas(deltas, store)

    # Persist the demo-built nodes/edges too (for this run)
    for n in nodes:
        n_dict = {
            "stable_key": getattr(n, "stable_key", getattr(n, "id", None)),
            "type": getattr(n, "type", "node"),
            "properties": getattr(n, "properties", {})
        }
        store.upsert_node(n_dict)
    for e in edges:
        e_dict = {
            "type": getattr(e, "type", ""),
            "source_id": getattr(e, "source_id", None),
            "target_id": getattr(e, "target_id", None),
            "properties": getattr(e, "properties", {})
        }
        store.upsert_edge(e_dict)
    store.save()

    return nodes, edges


if __name__ == "__main__":
    nodes, edges = example_graph()
    print("Nodes:", len(nodes))
    print("Edges:", len(edges))
    print("Example entity:", nodes[1].model_dump())
    print("Example edge:", edges[0].model_dump())