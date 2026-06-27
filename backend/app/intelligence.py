"""
Intelligence Feature

Central abstraction for **all** external and local LLM configurations.
Fully configuration-driven.

Capabilities:
- Smart model selection (choose_best) considering routing + strengths + **cost + latency**
- Native tool calling support (strategy per task in config)
- Automatic usage recording (latency, tokens, estimated cost) persisted to JSONL
- Beautiful Markdown reports with tables and cost/latency recommendations
- Works with xAI, OpenAI, Ollama, LM Studio, and any OpenAI-compatible endpoint

Usage:
    from intelligence import get_intelligence, TaskType

    intel = get_intelligence()
    best = intel.choose_best(TaskType.STRUCTURED_EXTRACTION)
    client = intel.get_client(TaskType.SEMANTIC_SEARCH)
    intel.save_report("data/intelligence/report.md")
"""

from __future__ import annotations

import os
import json
import time
import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional, List, Dict

from pydantic import BaseModel, Field
from openai import OpenAI


class TaskType(str, Enum):
    """Well-known tasks in the research platform where we invoke LLMs."""
    SEMANTIC_SEARCH = "semantic_search"           # Web/search style queries (Grok excels)
    STRUCTURED_EXTRACTION = "structured_extraction"  # JSON / entity+evidence graph deltas
    ENTITY_RESOLUTION = "entity_resolution"       # Fuzzy matching, deduping companies etc.
    CLASSIFICATION = "classification"             # Scope tagging, aspect classification
    GENERAL = "general"                           # Fallback / chat / summarization


class LLMConfig(BaseModel):
    """Normalized configuration for one LLM instance.

    Includes cost, latency, and tool-calling metadata for intelligent selection.
    """
    provider: str = Field(..., description="Logical provider name e.g. xai, openai, ollama")
    model: str = Field(..., description="Model name e.g. grok-3, gpt-4o, llama3.1")
    api_key: str = ""
    base_url: Optional[str] = None
    temperature: float = 0.1
    max_tokens: int = 2000
    supports_json_mode: bool = True

    # Cost & latency awareness (USD per million tokens)
    input_price_per_million: float = 0.0
    output_price_per_million: float = 0.0
    avg_latency_ms_per_1k: float = 500.0

    # Tool calling
    supports_tool_calling: bool = False

    # Free-form strengths for selection heuristics
    strengths: list[str] = Field(default_factory=list)


class Intelligence:
    """
    The Intelligence feature.

    - Owns all LLM configuration loading.
    - Knows how to pick the best model for a given task.
    - Provides ready-to-use OpenAI-compatible clients.
    """

    # Built-in default routing (used when config does not specify)
    DEFAULT_ROUTING: dict[TaskType, dict] = {
        TaskType.SEMANTIC_SEARCH: {
            "preferred": ["xai", "openai"],
            "fallback": "xai",
        },
        TaskType.STRUCTURED_EXTRACTION: {
            "preferred": ["xai", "openai"],
            "fallback": "xai",
            "requires_json": True,
        },
        TaskType.ENTITY_RESOLUTION: {
            "preferred": ["xai", "openai"],
            "fallback": "openai",
        },
        TaskType.CLASSIFICATION: {
            "preferred": ["xai", "openai"],
            "fallback": "xai",
        },
        TaskType.GENERAL: {
            "preferred": ["xai", "openai"],
            "fallback": "xai",
        },
    }

    # Rough capability map used for scoring when no explicit strengths are given
    KNOWN_STRENGTHS: dict[str, list[str]] = {
        "xai": ["search", "reasoning", "extraction", "tools", "json"],
        "grok-3": ["search", "reasoning", "extraction", "tools"],
        "grok-4": ["search", "reasoning", "extraction", "tools"],
        "openai": ["extraction", "json", "reasoning"],
        "gpt-4o": ["extraction", "json", "reasoning"],
        "gpt-4o-mini": ["speed", "cost", "extraction"],
    }

    def __init__(self, config_path: str = "data/config/llm.yaml"):
        self.config_path = config_path
        self._raw_config: dict[str, Any] = {}
        self._routing: dict[str, Any] = {}
        self._providers: dict[str, dict] = {}
        self._default_provider: str = "xai"

        # New: cost/latency + tool config driven data
        self._scoring: dict[str, float] = {"cost": 0.3, "latency": 0.2, "quality": 0.5}
        self._tool_strategies: dict[str, dict] = {}
        self._model_metadata: dict[str, dict] = {}   # key: "provider/model" or "model"

        # Usage persistence
        self._usage_dir = Path("data/intelligence")
        self._usage_file = self._usage_dir / "usage.jsonl"
        self._usage_dir.mkdir(parents=True, exist_ok=True)

        self._load()

    def _load(self) -> None:
        """Load (or reload) configuration from disk + merge env."""
        import yaml

        raw: dict = {}
        if os.path.exists(self.config_path):
            with open(self.config_path) as f:
                raw = yaml.safe_load(f) or {}

        # Also allow a flat "intelligence" top level or nested under it
        self._raw_config = raw
        self._default_provider = raw.get("default_provider", "xai")

        # Routing can live under "intelligence.routing" or top level "routing"
        intel_section = raw.get("intelligence", {}) or {}
        self._routing = intel_section.get("routing", {}) or raw.get("routing", {}) or {}

        # Scoring weights (cost/latency awareness)
        scoring = intel_section.get("scoring", {}) or {}
        if scoring:
            self._scoring = {
                "cost": float(scoring.get("cost_weight", 0.3)),
                "latency": float(scoring.get("latency_weight", 0.2)),
                "quality": float(scoring.get("quality_weight", 0.5)),
            }

        # Tool calling strategies (config driven)
        self._tool_strategies = intel_section.get("tool_strategies", {}) or {}

        # Model metadata for pricing / latency / capabilities
        self._model_metadata = intel_section.get("models", {}) or {}

        # Providers section (the heart of external + local configs)
        self._providers = raw.get("providers", {}) or {}

        # Support very simple top-level provider keys for convenience
        for key in ("xai", "openai", "ollama", "local"):
            if key in raw and isinstance(raw[key], dict) and key not in self._providers:
                self._providers[key] = raw[key]

    def reload(self) -> None:
        """Force reload from disk (useful after editing llm.yaml)."""
        self._load()

    # ------------------------------------------------------------------
    # Configuration access
    # ------------------------------------------------------------------

    def get_raw_config(self) -> dict:
        return dict(self._raw_config)

    def get_provider_raw(self, provider: str) -> dict:
        """Raw dict for a provider (before env merge)."""
        prov = self._providers.get(provider, {}) or {}
        if not prov:
            # support flat at root
            prov = self._raw_config.get(provider, {}) or {}
        return dict(prov)

    def _resolve_env_key(self, provider: str) -> Optional[str]:
        """Check common environment variable patterns for the API key."""
        candidates = [
            f"{provider.upper()}_API_KEY",
            f"LLM_{provider.upper()}_API_KEY",
            "XAI_API_KEY" if provider == "xai" else None,
            "OPENAI_API_KEY" if provider in ("openai", "gpt") else None,
        ]
        for name in candidates:
            if name:
                val = os.getenv(name)
                if val:
                    return val
        return None

    def get_resolved_provider(self, provider: str) -> dict:
        """
        Return fully resolved provider config:
        - env vars override file
        - sensible defaults applied
        - cost, latency and tool metadata merged from intelligence.models
        """
        raw = self.get_provider_raw(provider)

        api_key = self._resolve_env_key(provider) or raw.get("api_key", "")

        result = {
            "api_key": api_key,
            "base_url": raw.get("base_url", ""),
            "default_model": raw.get("default_model", ""),
            "temperature": raw.get("temperature", 0.1),
            "max_tokens": raw.get("max_tokens", 2000),
            "supports_json_mode": raw.get("supports_json_mode", True),
            "input_price_per_million": 0.0,
            "output_price_per_million": 0.0,
            "avg_latency_ms_per_1k": 500.0,
            "supports_tool_calling": False,
        }

        # Provider-specific defaults
        if provider in ("xai", "xai-grok"):
            result.setdefault("base_url", "https://api.x.ai/v1")
            result.setdefault("default_model", "grok-3")
        elif provider == "openai":
            result.setdefault("base_url", "https://api.openai.com/v1")
            result.setdefault("default_model", "gpt-4o")
        elif provider in ("ollama", "local", "lmstudio"):
            # Ollama and most local servers use dummy key + local base_url
            result.setdefault("base_url", "http://localhost:11434/v1")
            result.setdefault("default_model", "llama3.1")
            result.setdefault("api_key", "ollama")  # many local servers ignore key
            result["supports_json_mode"] = raw.get("supports_json_mode", True)

        # Allow per-provider model list or single default_model
        if "models" in raw and isinstance(raw["models"], list) and not result["default_model"]:
            result["default_model"] = raw["models"][0]

        # Merge pricing / latency / tool info from central model registry (config driven)
        model_key = f"{provider}/{result['default_model']}"
        meta = self._model_metadata.get(model_key) or self._model_metadata.get(result["default_model"], {}) or {}
        result["input_price_per_million"] = float(meta.get("input_price_per_million", result["input_price_per_million"]))
        result["output_price_per_million"] = float(meta.get("output_price_per_million", result["output_price_per_million"]))
        result["avg_latency_ms_per_1k"] = float(meta.get("avg_latency_ms_per_1k", result["avg_latency_ms_per_1k"]))
        result["supports_tool_calling"] = bool(meta.get("supports_tool_calling", result.get("supports_tool_calling", False)))

        # Also allow direct keys on the provider definition
        for k in ("input_price_per_million", "output_price_per_million", "avg_latency_ms_per_1k", "supports_tool_calling"):
            if k in raw:
                result[k] = raw[k]

        return result

    # ------------------------------------------------------------------
    # Model selection / "Intelligence"
    # ------------------------------------------------------------------

    def _get_routing_for_task(self, task: TaskType) -> dict:
        """Get routing preferences for a task (from config or defaults)."""
        task_key = task.value
        explicit = self._routing.get(task_key) or self._routing.get(task_key.replace("_", "-"), {})
        if explicit:
            return dict(explicit)

        # Fall back to built-in defaults
        return dict(self.DEFAULT_ROUTING.get(task, self.DEFAULT_ROUTING[TaskType.GENERAL]))

    def _score_candidate(self, provider: str, model: str, task: TaskType, routing: dict) -> float:
        """Heuristic score for how good a (provider, model) is for a task.

        Now includes cost and latency awareness (configuration driven).
        """
        score = 0.0

        preferred = routing.get("preferred", []) or []
        # Exact provider match in preferred list
        if provider in preferred:
            score += 3.0
        # Preferred can contain "provider/model" strings too
        for pref in preferred:
            if "/" in pref and pref.startswith(provider):
                score += 2.5

        # Task-specific bonuses
        if task == TaskType.SEMANTIC_SEARCH:
            if "xai" in provider or "grok" in model.lower():
                score += 2.0
            if "search" in self.KNOWN_STRENGTHS.get(provider, []):
                score += 1.0

        if task in (TaskType.STRUCTURED_EXTRACTION, TaskType.ENTITY_RESOLUTION):
            if "json" in self.KNOWN_STRENGTHS.get(model, []) or "extraction" in self.KNOWN_STRENGTHS.get(model, []):
                score += 2.0
            if routing.get("requires_json"):
                # Bonus if we know it supports json mode
                prov_cfg = self.get_resolved_provider(provider)
                if prov_cfg.get("supports_json_mode", True):
                    score += 1.0

        # Strength match from config or known map
        strengths = self.KNOWN_STRENGTHS.get(provider, []) + self.KNOWN_STRENGTHS.get(model, [])
        task_keywords = {
            TaskType.SEMANTIC_SEARCH: ["search", "tools"],
            TaskType.STRUCTURED_EXTRACTION: ["extraction", "json"],
            TaskType.ENTITY_RESOLUTION: ["extraction", "json", "reasoning"],
            TaskType.CLASSIFICATION: ["classification", "reasoning"],
            TaskType.GENERAL: ["reasoning"],
        }.get(task, [])
        for kw in task_keywords:
            if kw in strengths:
                score += 0.8

        # Prefer models explicitly marked strong for this task in config
        raw_prov = self.get_provider_raw(provider)
        model_strengths = raw_prov.get("strengths", []) or []
        if any(kw in model_strengths for kw in task_keywords):
            score += 1.5

        # Small penalty for very small/fast models on hard tasks (simple heuristic)
        if "mini" in model.lower() and task in (TaskType.STRUCTURED_EXTRACTION, TaskType.SEMANTIC_SEARCH):
            score -= 0.5

        # === Cost / Latency awareness (the new intelligence) ===
        resolved = self.get_resolved_provider(provider)
        # Use resolved + model metadata
        in_p = float(resolved.get("input_price_per_million", 0))
        out_p = float(resolved.get("output_price_per_million", 0))
        avg_cost = (in_p + out_p) / 2.0

        lat = float(resolved.get("avg_latency_ms_per_1k", resolved.get("avg_latency_ms_per_1k", 500)))

        # Normalize roughly (higher cost/latency = lower score)
        # Tuned scales so they are meaningful relative to quality points
        cost_penalty = (avg_cost / 8.0) * self._scoring.get("cost", 0.3) * 4.0
        latency_penalty = (lat / 1200.0) * self._scoring.get("latency", 0.2) * 4.0

        score -= cost_penalty
        score -= latency_penalty

        # Bonus for free / very low cost or fast local models when appropriate
        if avg_cost < 0.1:
            score += 0.6 * (1 - self._scoring.get("cost", 0.3))
        if lat < 400:
            score += 0.4

        return max(0.0, score)

    def choose_best(self, task: TaskType = TaskType.GENERAL, **hints: Any) -> LLMConfig:
        """
        The core "intelligence" method.

        Returns the best LLMConfig for the given task, considering:
        - Explicit routing in llm.yaml (intelligence.routing.<task>)
        - Built-in knowledge of model capabilities
        - Availability of API keys / base_url
        - Fallbacks
        """
        routing = self._get_routing_for_task(task)

        # Build ordered list of candidate providers
        candidates: list[str] = []

        # 1. Explicit preferred from config
        for p in routing.get("preferred", []) or []:
            # support "provider" or "provider/model"
            name = p.split("/")[0]
            if name not in candidates:
                candidates.append(name)

        # 2. Default provider
        if self._default_provider not in candidates:
            candidates.append(self._default_provider)

        # 3. Any other providers that have keys (as last resort)
        for p in list(self._providers.keys()):
            if p not in candidates:
                candidates.append(p)

        # Also consider common local names if user configured them
        for local_name in ("ollama", "local", "lmstudio", "vllm"):
            if local_name in self._providers and local_name not in candidates:
                candidates.append(local_name)

        best: Optional[LLMConfig] = None
        best_score = -1.0

        for prov_name in candidates:
            resolved = self.get_resolved_provider(prov_name)
            api_key = resolved.get("api_key", "")
            base_url = resolved.get("base_url")

            # Must have either a real key or a base_url (local servers)
            has_credential = bool(api_key) or bool(base_url)
            if not has_credential:
                continue

            model_name = resolved.get("default_model") or "default"
            score = self._score_candidate(prov_name, model_name, task, routing)

            # Allow hints to boost certain providers
            hint_boost = hints.get("boost_providers", {}) or {}
            if prov_name in hint_boost:
                score += float(hint_boost[prov_name])

            if score > best_score:
                best_score = score
                best = LLMConfig(
                    provider=prov_name,
                    model=model_name,
                    api_key=api_key,
                    base_url=base_url or None,
                    temperature=resolved.get("temperature", 0.1),
                    max_tokens=resolved.get("max_tokens", 2000),
                    supports_json_mode=resolved.get("supports_json_mode", True),
                    input_price_per_million=resolved.get("input_price_per_million", 0.0),
                    output_price_per_million=resolved.get("output_price_per_million", 0.0),
                    avg_latency_ms_per_1k=resolved.get("avg_latency_ms_per_1k", 500.0),
                    supports_tool_calling=resolved.get("supports_tool_calling", False),
                    strengths=self.KNOWN_STRENGTHS.get(prov_name, []) + self.KNOWN_STRENGTHS.get(model_name, []),
                )

        if best is None:
            # Last-ditch attempt using default
            resolved = self.get_resolved_provider(self._default_provider)
            best = LLMConfig(
                provider=self._default_provider,
                model=resolved.get("default_model", "grok-3"),
                api_key=resolved.get("api_key", ""),
                base_url=resolved.get("base_url") or None,
                temperature=resolved.get("temperature", 0.1),
                max_tokens=resolved.get("max_tokens", 2000),
                input_price_per_million=resolved.get("input_price_per_million", 0.0),
                output_price_per_million=resolved.get("output_price_per_million", 0.0),
                avg_latency_ms_per_1k=resolved.get("avg_latency_ms_per_1k", 500.0),
                supports_tool_calling=resolved.get("supports_tool_calling", False),
            )

        return best

    # ------------------------------------------------------------------
    # Client factory
    # ------------------------------------------------------------------

    def get_client(self, task: TaskType = TaskType.GENERAL) -> OpenAI:
        """Return a ready-to-use OpenAI-compatible client for the best model for the task."""
        chosen = self.choose_best(task)
        if not chosen.api_key and not chosen.base_url:
            raise ValueError(
                f"No API key or base_url available for task={task.value}. "
                f"Check data/config/llm.yaml or set the appropriate *_API_KEY env var."
            )
        return OpenAI(
            api_key=chosen.api_key or "dummy",
            base_url=chosen.base_url,
        )

    def get_model_info(self, task: TaskType = TaskType.GENERAL) -> LLMConfig:
        """Return the chosen model metadata without creating a client."""
        return self.choose_best(task)

    def _get_tool_strategy(self, task: TaskType) -> str:
        """Return the configured tool calling strategy for a task."""
        task_key = task.value
        cfg = self._tool_strategies.get(task_key) or self._tool_strategies.get(task_key.replace("_", "-"), {})
        return cfg.get("strategy", "native_if_available") if isinstance(cfg, dict) else "native_if_available"

    def get_tool_strategy(self, task: TaskType) -> str:
        """Public version of tool strategy lookup."""
        return self._get_tool_strategy(task)

    # ------------------------------------------------------------------
    # Convenience high-level calls + Tool calling + Usage tracking
    # ------------------------------------------------------------------

    def complete(
        self,
        task: TaskType,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> Any:
        """Chat completion using the best model for the task.

        Supports tool calling when:
          - strategy allows (config driven)
          - the chosen model declares supports_tool_calling
        """
        client = self.get_client(task)
        info = self.choose_best(task)
        model = info.model
        temperature = kwargs.pop("temperature", info.temperature)
        max_tokens = kwargs.pop("max_tokens", info.max_tokens)

        strategy = self._get_tool_strategy(task)
        use_native_tools = (
            tools and
            strategy in ("native_if_available", "native") and
            getattr(info, "supports_tool_calling", False)
        )

        start = time.time()
        try:
            call_kwargs = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            call_kwargs.update(kwargs)

            if use_native_tools:
                call_kwargs["tools"] = tools
                call_kwargs["tool_choice"] = tool_choice

            resp = client.chat.completions.create(**call_kwargs)
            latency_ms = (time.time() - start) * 1000

            # Auto-record usage (cost + latency awareness)
            self._record_usage_from_response(task, info, resp, latency_ms)

            return resp
        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            self._record_raw_usage(task, info, latency_ms, error=str(e))
            raise

    def extract_structured(
        self,
        task: TaskType,
        system: str,
        user: str,
        **kwargs: Any,
    ) -> dict:
        """Helper for tasks that want JSON output (used heavily by discovery)."""
        client = self.get_client(task)
        info = self.choose_best(task)

        start = time.time()
        try:
            resp = client.chat.completions.create(
                model=info.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=kwargs.pop("temperature", info.temperature),
                max_tokens=kwargs.pop("max_tokens", info.max_tokens),
                response_format={"type": "json_object"} if info.supports_json_mode else None,
                **kwargs,
            )
            latency_ms = (time.time() - start) * 1000
            self._record_usage_from_response(task, info, resp, latency_ms)

            content = resp.choices[0].message.content.strip()
            # Basic cleanup (can be improved)
            if content.startswith("```"):
                content = content.split("```")[1].strip()
                if content.lower().startswith("json"):
                    content = content[4:].strip()
            return json.loads(content)
        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            self._record_raw_usage(task, info, latency_ms, error=str(e))
            print(f"[intelligence] Structured extraction failed: {e}")
            return {}

    # ------------------------------------------------------------------
    # Usage recording (cost + latency) with persistence
    # ------------------------------------------------------------------

    def _estimate_cost(self, info: LLMConfig, input_tokens: int = 0, output_tokens: int = 0) -> float:
        cost = (input_tokens / 1_000_000.0) * info.input_price_per_million
        cost += (output_tokens / 1_000_000.0) * info.output_price_per_million
        return round(cost, 6)

    def _record_usage_from_response(self, task: TaskType, info: LLMConfig, response: Any, latency_ms: float):
        """Record real usage when OpenAI response object is available."""
        usage = getattr(response, "usage", None)
        in_tok = getattr(usage, "prompt_tokens", 0) if usage else 0
        out_tok = getattr(usage, "completion_tokens", 0) if usage else 0

        record = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "task": task.value,
            "provider": info.provider,
            "model": info.model,
            "latency_ms": round(latency_ms, 1),
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "estimated_cost": self._estimate_cost(info, in_tok, out_tok),
            "tool_calls": 0,
        }

        # Detect tool calls if present
        try:
            choices = getattr(response, "choices", [])
            if choices and getattr(choices[0].message, "tool_calls", None):
                record["tool_calls"] = len(choices[0].message.tool_calls or [])
        except Exception:
            pass

        self._append_usage(record)

    def _record_raw_usage(self, task: TaskType, info: LLMConfig, latency_ms: float, error: Optional[str] = None, **extra):
        in_tok = extra.pop("input_tokens", 0)
        out_tok = extra.pop("output_tokens", 0)

        record = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "task": task.value,
            "provider": info.provider,
            "model": info.model,
            "latency_ms": round(latency_ms, 1),
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "estimated_cost": self._estimate_cost(info, in_tok, out_tok),
            "tool_calls": 0,
            "error": error,
        }
        record.update(extra)
        self._append_usage(record)

    def _append_usage(self, record: dict):
        try:
            with open(self._usage_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[intelligence] Failed to persist usage: {e}")

    def load_usage(self, limit: Optional[int] = None) -> List[dict]:
        """Load persisted usage records (most recent first if limit given)."""
        records = []
        if not self._usage_file.exists():
            return records
        try:
            with open(self._usage_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        except Exception:
            pass
        if limit:
            records = records[-limit:]
        return records

    # ------------------------------------------------------------------
    # Visual reporting with proper formatting (Markdown tables etc.)
    # ------------------------------------------------------------------

    def get_usage_report(self, limit: Optional[int] = 500) -> str:
        """Return a nicely formatted Markdown report of LLM usage, cost and latency."""
        records = self.load_usage(limit)
        if not records:
            return "# LLM Intelligence Usage Report\n\nNo usage data recorded yet."

        total_calls = len(records)
        total_cost = sum(r.get("estimated_cost", 0) for r in records)
        total_tokens_in = sum(r.get("input_tokens", 0) for r in records)
        total_tokens_out = sum(r.get("output_tokens", 0) for r in records)

        # Aggregate by model
        by_model: Dict[str, Dict] = {}
        by_task: Dict[str, Dict] = {}

        for r in records:
            key = f"{r.get('provider')}/{r.get('model')}"
            if key not in by_model:
                by_model[key] = {"calls": 0, "cost": 0.0, "latencies": [], "in": 0, "out": 0}
            m = by_model[key]
            m["calls"] += 1
            m["cost"] += r.get("estimated_cost", 0)
            if r.get("latency_ms"):
                m["latencies"].append(r["latency_ms"])
            m["in"] += r.get("input_tokens", 0)
            m["out"] += r.get("output_tokens", 0)

            tk = r.get("task", "unknown")
            if tk not in by_task:
                by_task[tk] = {"calls": 0, "cost": 0.0, "latencies": []}
            t = by_task[tk]
            t["calls"] += 1
            t["cost"] += r.get("estimated_cost", 0)
            if r.get("latency_ms"):
                t["latencies"].append(r["latency_ms"])

        lines = []
        lines.append("# LLM Intelligence Usage Report")
        lines.append(f"\n_Generated: {datetime.datetime.utcnow().isoformat()}Z_")
        lines.append("\n## Summary")
        lines.append(f"- **Total calls**: {total_calls}")
        lines.append(f"- **Total estimated cost**: ${total_cost:.6f}")
        lines.append(f"- **Total input tokens**: {total_tokens_in:,}")
        lines.append(f"- **Total output tokens**: {total_tokens_out:,}")
        if total_calls > 0:
            avg_lat = sum(r.get("latency_ms", 0) for r in records) / total_calls
            lines.append(f"- **Average latency**: {avg_lat:.0f} ms")

        # By model table
        lines.append("\n## By Model")
        lines.append("| Provider / Model | Calls | Est. Cost | Avg Latency (ms) | Total Tokens |")
        lines.append("|------------------|-------|-----------|------------------|--------------|")
        for key, stats in sorted(by_model.items(), key=lambda x: -x[1]["cost"]):
            avg_l = (sum(stats["latencies"]) / len(stats["latencies"])) if stats["latencies"] else 0
            tot_tok = stats["in"] + stats["out"]
            lines.append(f"| {key} | {stats['calls']} | ${stats['cost']:.6f} | {avg_l:.0f} | {tot_tok:,} |")

        # By task table
        lines.append("\n## By Task")
        lines.append("| Task | Calls | Est. Cost | Avg Latency (ms) |")
        lines.append("|------|-------|-----------|------------------|")
        for task, stats in sorted(by_task.items()):
            avg_l = (sum(stats["latencies"]) / len(stats["latencies"])) if stats["latencies"] else 0
            lines.append(f"| {task} | {stats['calls']} | ${stats['cost']:.6f} | {avg_l:.0f} |")

        # Recommendations
        lines.append("\n## Recommendations (cost / latency aware)")
        if total_cost > 0:
            cheapest = min(by_model.items(), key=lambda x: x[1]["cost"] / max(x[1]["calls"], 1))
            lines.append(f"- Cheapest per call on average: **{cheapest[0]}**")
        fast = min(
            ( (k, sum(v["latencies"])/len(v["latencies"])) for k,v in by_model.items() if v["latencies"] ),
            key=lambda x: x[1],
            default=None
        )
        if fast:
            lines.append(f"- Fastest observed: **{fast[0]}** ({fast[1]:.0f} ms avg)")

        return "\n".join(lines)

    def save_report(self, path: str = "data/intelligence/report.md") -> str:
        """Generate and save a nicely formatted report."""
        report = self.get_usage_report()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"[intelligence] Report saved to {path}")
        return report

    def print_usage_report(self):
        """Convenience: print the current report to stdout."""
        print(self.get_usage_report())


# ----------------------------------------------------------------------
# Module-level convenience (singleton pattern)
# ----------------------------------------------------------------------

_default_intelligence: Optional[Intelligence] = None


def get_intelligence(config_path: str = "data/config/llm.yaml") -> Intelligence:
    """Return a (cached) Intelligence instance. Use this everywhere."""
    global _default_intelligence
    if _default_intelligence is None or _default_intelligence.config_path != config_path:
        _default_intelligence = Intelligence(config_path)
    return _default_intelligence


def choose_best_model(task: TaskType = TaskType.GENERAL, **hints: Any) -> LLMConfig:
    """Shortcut to pick the best model for a task."""
    return get_intelligence().choose_best(task, **hints)


# ----------------------------------------------------------------------
# Example tool schemas (used when tool strategy = native_if_available)
# ----------------------------------------------------------------------

SEMANTIC_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search_recent",
        "description": "Search the web for recent news, product launches, milestones and developments matching the query.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query, e.g. 'SpaceX Starship test flight results 2025'"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 10)"
                }
            },
            "required": ["query"]
        }
    }
}


def get_llm_client(task: TaskType = TaskType.GENERAL) -> OpenAI:
    """Shortcut to get a client tuned for a task."""
    return get_intelligence().get_client(task)


# Backwards-compatible aliases used by older code
def load_llm_config(config_path: str = "data/config/llm.yaml") -> dict:
    return get_intelligence(config_path).get_raw_config()


def get_provider_config(provider: str = "xai") -> dict:
    return get_intelligence().get_resolved_provider(provider)
