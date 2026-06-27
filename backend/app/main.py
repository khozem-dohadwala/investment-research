from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
import yaml
from .routers import discovery
from .models.graph import (
    load_scopes_from_config,
    discover_developments,
    GraphStore,
    upsert_graph_deltas,
    ScopeNode,
)

# New Intelligence feature (recommended)
from intelligence import get_intelligence, TaskType, load_llm_config, get_provider_config

app = FastAPI(title="Research Platform API")

app.include_router(discovery.router)

# Simple in-memory store (in prod use singleton or DB)
store = GraphStore()

scheduler = BackgroundScheduler()

def _load_scopes():
    return load_scopes_from_config()

def scheduled_discovery():
    print("[scheduler] Running periodic discovery...")
    config = _load_scopes()
    discovery_cfg = config.get("discovery", {})
    if not discovery_cfg.get("enabled", True):
        return
    for top in config.get("top_level_scopes", []):
        scope = ScopeNode(
            stable_key=top["stable_key"],
            properties={k: v for k, v in top.items() if k not in ["children"]}
        )
        try:
            deltas = discover_developments(scope, use_real_search=discovery_cfg.get("use_real_search", True), config=config)
            upsert_graph_deltas(deltas, store)
        except Exception as e:
            print(f"[scheduler] Error for {top['stable_key']}: {e}")

@app.on_event("startup")
def startup_event():
    # Load initial
    config = _load_scopes()

    # Intelligence feature: shows which models would be chosen for key tasks
    # (now cost + latency aware and tool-calling capable)
    intel = get_intelligence()
    intel_cfg = intel.get_raw_config()
    search_model = intel.choose_best(TaskType.SEMANTIC_SEARCH)
    extract_model = intel.choose_best(TaskType.STRUCTURED_EXTRACTION)

    cron = config.get("discovery", {}).get("refresh_cron", "0 */4 * * *")
    scheduler.add_job(scheduled_discovery, "cron", **_parse_cron(cron))
    scheduler.start()

    print("[startup] Intelligence loaded (cost/latency + tool-calling aware). default_provider:", intel_cfg.get("default_provider"))
    print("           Best for search:", search_model.provider, "/", search_model.model,
          f"(~${(search_model.input_price_per_million + search_model.output_price_per_million)/2:.2f}/M tok, {search_model.avg_latency_ms_per_1k:.0f}ms/1k)")
    print("           Best for extraction:", extract_model.provider, "/", extract_model.model,
          f"(~${(extract_model.input_price_per_million + extract_model.output_price_per_million)/2:.2f}/M tok, {extract_model.avg_latency_ms_per_1k:.0f}ms/1k)")
    print("[scheduler] Started with cron:", cron)

def _parse_cron(cron: str):
    # Very simple parser for "0 */4 * * *"
    parts = cron.split()
    if len(parts) != 5:
        return {"minute": "0", "hour": "*/4"}
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }

@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
