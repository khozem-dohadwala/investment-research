# Intelligence Usage Data

This directory contains runtime data collected by the Intelligence feature:

- `usage.jsonl` — newline-delimited JSON records of every LLM call (task, provider, model, latency, tokens, estimated cost, tool calls)
- `report.md` — human-readable Markdown report with formatted tables (Summary, By Model, By Task, Recommendations)

## Generating a fresh report

```bash
PYTHONPATH=backend/app python3 -c '
from intelligence import get_intelligence
intel = get_intelligence()
intel.save_report("data/intelligence/report.md")
print(intel.get_usage_report())
'
```

All cost/latency/tool calling behaviour is driven from `data/config/llm.yaml` under the `intelligence:` key (scoring weights, tool_strategies, models pricing).