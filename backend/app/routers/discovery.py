from fastapi import APIRouter, BackgroundTasks, HTTPException
from typing import Optional
from ..models.graph import (
    load_scopes_from_config,
    discover_developments,
    GraphStore,
    upsert_graph_deltas,
    ScopeNode,
)

from intelligence import get_intelligence, TaskType

router = APIRouter(prefix="/discovery", tags=["discovery"])

# In real app, inject store
store = GraphStore()

@router.post("/run")
async def run_discovery(
    scope_slug: str,
    aspects: Optional[list[str]] = None,
    background_tasks: BackgroundTasks = None,
):
    """Trigger discovery for a scope (sub-domain or area)."""
    config = load_scopes_from_config()
    # Simple lookup for top level for demo; in prod walk the tree
    target_scope = None
    for top in config.get("top_level_scopes", []):
        if top["stable_key"] == scope_slug:
            target_scope = ScopeNode(
                stable_key=top["stable_key"],
                properties={k: v for k, v in top.items() if k not in ["children", "search_queries"]}
            )
            break
        for child in top.get("children", []):
            if child["stable_key"] == scope_slug:
                target_scope = ScopeNode(
                    stable_key=child["stable_key"],
                    properties={k: v for k, v in child.items() if k != "children"}
                )
                break

    if not target_scope:
        raise HTTPException(status_code=404, detail=f"Scope {scope_slug} not found")

    if background_tasks:
        background_tasks.add_task(_run_discovery_task, target_scope, aspects or ["technology", "events"])
        return {"status": "discovery queued", "scope": scope_slug}
    else:
        deltas = discover_developments(target_scope, aspects or ["technology", "events"], use_real_search=True, config=config)
        upsert_graph_deltas(deltas, store)

        # Show which LLM the Intelligence feature actually used (incl. cost/latency data)
        intel = get_intelligence()
        used_model = intel.choose_best(TaskType.STRUCTURED_EXTRACTION)
        return {
            "status": "completed",
            "scope": scope_slug,
            "deltas": deltas,
            "intelligence": {
                "provider": used_model.provider,
                "model": used_model.model,
                "task": TaskType.STRUCTURED_EXTRACTION.value,
                "est_cost_per_mtok": round(used_model.input_price_per_million + used_model.output_price_per_million, 2),
                "avg_latency_ms_per_1k": used_model.avg_latency_ms_per_1k,
                "supports_tool_calling": used_model.supports_tool_calling,
            },
        }


def _run_discovery_task(scope: ScopeNode, aspects: list[str]):
    config = load_scopes_from_config()
    deltas = discover_developments(scope, aspects, use_real_search=True, config=config)
    upsert_graph_deltas(deltas, store)

    intel = get_intelligence()
    used = intel.choose_best(TaskType.STRUCTURED_EXTRACTION)
    print(f"[discovery] Intelligence used {used.provider}/{used.model} for extraction")
