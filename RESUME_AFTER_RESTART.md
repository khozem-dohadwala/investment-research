# Resume Development After Restart

**Project:** /Users/kd/InvestmentResearch  
**Last saved:** 2026-06-27 (before computer restart)

> **New!** Use the `grok` command for almost everything.

```bash
grok resume     # ← Start here after a restart
```

## Quick Status

- **Graph:** 410 nodes / 1019 edges (Space + other industries fully populated)
- **Intelligence feature:** Fully implemented with cost/latency awareness + tool calling
- **Usage data:** 5 sample records tracked (with cost + latency)
- **Config:** `data/config/llm.yaml` has xAI key + pricing + routing + tool strategies

## Critical Files (must survive restart)

```
data/graph.db                 ← Main SQLite store (most important)
data/graph.json               ← Portable snapshot
data/config/scopes.yaml       ← Hierarchy + discovery queries
data/config/llm.yaml          ← LLM keys + Intelligence config (secrets!)
data/intelligence/            ← Usage history + reports
backend/app/intelligence.py   ← The Intelligence feature code
```

**Note:** `data/config/llm.yaml` contains your XAI_API_KEY. It is gitignored.

---

## Commands to Resume (run in this order)

### 1. Go to the project (and make grok command available)

```bash
cd /Users/kd/InvestmentResearch

# Optional: make `grok` command available without ./
export PATH="$PWD:$PATH"
```

Now you can just type `grok` commands!

### 2. Use the simple `grok` commands (recommended)

```bash
grok resume          # ← Main command after computer restart
grok status
grok report
grok save
grok discover space-industry
```

This replaces all the old long PYTHONPATH commands.

### 3. Use these instead of the old long commands

```bash
grok status
grok report
grok save
grok discover space-industry
```

All the old `PYTHONPATH=backend/app python3 -c '...'` one-liners are now wrapped in the `grok` command.

### 4. Bonus: Quick one-liners (still available via grok)

```bash
grok status
grok report
grok shell          # drops you into a Python REPL with correct paths
```

---

## After Computer Restart Checklist

1. `cd /Users/kd/InvestmentResearch`
2. (Optional) `PYTHONPATH=backend/app python3 restore_graph.py` or the import_json command above
3. Check Intelligence: run the status snippet in section 4
4. Start making changes in `backend/app/intelligence.py` or `data/config/llm.yaml`
5. Use `intel.save_report()` frequently when experimenting with cost/latency/tool features

## Useful Files

- `RESUME_AFTER_RESTART.md` (this file)
- `data/intelligence/README.md`
- `save_graph.py` / `restore_graph.py`
- `data/config/llm.yaml.example` (safe template)

You can safely restart now. All important state is persisted.