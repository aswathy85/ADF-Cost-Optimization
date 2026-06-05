"""genai_optimizer.py — Produce optimization suggestions using GenAI or rule-based fallbacks.

Primary entrypoint: `run_ai_optimization(payload, cfg)` which will attempt to
call the configured GenAI provider (Anthropic) and return a list of
`OptimizationSuggestion` objects. If no API key is configured, a small set
of deterministic, rule-based suggestions is used instead.
"""
from __future__ import annotations
import json, logging, os
from typing import List
from src.config import AppConfig
from src.models import OptimizationSuggestion, PipelineRecord, ReportPayload

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a senior Azure Data Factory (ADF) architect and cost optimization expert.

You analyse ADF pipeline definitions and their run metrics to identify cost optimisation opportunities.
You understand:
- ADF pricing: Copy activity ($0.25/DIU-hour), Mapping Data Flow ($0.274/DIU-hour), activity runs ($0.001/run)
- How DIU settings directly multiply cost; best practices: delta/incremental load, parallelism, IR selection
- Data Flow optimisation: partition schemes, broadcast hints, Quick Reuse IR setting
- Pipeline structure: reducing redundant activities, ForEach batch size, caching Lookup results

Return ONLY a valid JSON array. Each element represents ONE optimisation suggestion with these exact keys:
{
  "issue_category": "<High DIU Setting | Full Load Instead of Delta | Unoptimised Data Flow | Excessive Activity Runs | No Parallelism | Redundant Activities | Wrong IR Type | Large Data Movement | Missing Caching | Inefficient Sink>",
  "issue_description": "<1-2 sentences describing the specific issue>",
  "suggestion": "<2-4 sentences with specific actionable change including exact values>",
  "estimated_saving_pct": <float 0-80>,
  "priority": "<High|Medium|Low>",
  "effort": "<High|Medium|Low>",
  "optimized_code_snippet": "<key JSON property showing the optimized change>"
}
Rules: Return ONLY the JSON array, no markdown. Give 2-5 suggestions. estimated_saving_pct must be realistic."""

_USER_TEMPLATE = """Analyse this ADF pipeline and suggest cost optimisations.

Pipeline: {pipeline_name}
Factory: {factory_name} | Environment: {environment}
Current cost (last {days} days): ${current_cost_usd:.2f} | Run count: {run_count}
Average duration: {avg_duration_min:.1f} min
Pipeline purpose: {description}

Pipeline definition:
{pipeline_json}

Activity summary:
{activity_summary}

Return optimisation suggestions as JSON array only."""


def run_ai_optimization(payload: ReportPayload, cfg: AppConfig) -> List[OptimizationSuggestion]:
    """Run GenAI analysis for the top pipelines and return suggestions.

    - If `ANTHROPIC_API_KEY` is not configured, fall back to a rule-based analyzer.
    - Limits analysis to `cfg.analysis.top_pipelines_for_ai` most expensive pipelines.
    """
    api_key = cfg.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("No ANTHROPIC_API_KEY — using rule-based suggestions")
        return _fallback_suggestions(payload, cfg)

    all_pipelines = sorted(
        [p for f in payload.factories for p in f.pipelines],
        key=lambda p: p.estimated_cost_usd, reverse=True,
    )[: cfg.analysis.top_pipelines_for_ai]

    suggestions: List[OptimizationSuggestion] = []
    for idx, pipeline in enumerate(all_pipelines, 1):
        logger.info("🤖 AI %d/%d — %s ($%.2f)", idx, len(all_pipelines), pipeline.pipeline_name, pipeline.estimated_cost_usd)
        try:
            suggestions.extend(_analyze_pipeline(pipeline, payload.date_range_days, cfg, api_key))
        except Exception as exc:
            logger.error("AI failed for %s: %s", pipeline.pipeline_name, exc)
            suggestions.extend(_rule_based_for_pipeline(pipeline, cfg))
    return suggestions


def _analyze_pipeline(pipeline: PipelineRecord, days: int, cfg: AppConfig, api_key: str) -> List[OptimizationSuggestion]:
    """Call the Anthropic API to analyze a single pipeline and parse suggestions.

    Builds a concise user prompt including pipeline JSON (truncated if large)
    and activity summaries, then converts the returned JSON array into
    `OptimizationSuggestion` instances.
    """
    import anthropic
    act_lines = [f"  - {a.activity_name} [{a.activity_type}] | Cost: ${a.estimated_cost_usd:.2f} | Runs: {a.run_count}"
                 for a in pipeline.activities]
    description = pipeline.definition.get("properties", {}).get("description", "No description provided.")
    pl_json = json.dumps(pipeline.definition, indent=2)
    if len(pl_json) > 6000:
        pl_json = pl_json[:6000] + "\n...[truncated]"
    user_msg = _USER_TEMPLATE.format(
        pipeline_name=pipeline.pipeline_name, factory_name=pipeline.factory_name,
        environment=pipeline.environment, current_cost_usd=pipeline.estimated_cost_usd,
        days=days, run_count=pipeline.run_count,
        avg_duration_min=pipeline.avg_duration_sec / 60, description=description,
        pipeline_json=pl_json, activity_summary="\n".join(act_lines) or "  No activities.",
    )
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=cfg.genai.model, max_tokens=cfg.genai.max_tokens,
        system=_SYSTEM_PROMPT, messages=[{"role": "user", "content": user_msg}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
    raw = raw.strip()
    results = []
    for item in json.loads(raw):
        saving_pct = float(item.get("estimated_saving_pct", 0))
        snippet = item.get("optimized_code_snippet", "")
        results.append(OptimizationSuggestion(
            pipeline_name=pipeline.pipeline_name, factory_name=pipeline.factory_name,
            environment=pipeline.environment, current_cost_usd=pipeline.estimated_cost_usd,
            issue_category=item.get("issue_category", "General"),
            issue_description=item.get("issue_description", ""),
            suggestion=item.get("suggestion", ""),
            estimated_saving_pct=saving_pct,
            estimated_saving_usd=round(pipeline.estimated_cost_usd * saving_pct / 100, 2),
            priority=item.get("priority", "Medium"), effort=item.get("effort", "Medium"),
            optimized_code_snippet=json.dumps(snippet, indent=2) if isinstance(snippet, dict) else str(snippet),
        ))
    return results


def _fallback_suggestions(payload: ReportPayload, cfg: AppConfig) -> List[OptimizationSuggestion]:
    all_pipelines = sorted([p for f in payload.factories for p in f.pipelines],
                           key=lambda p: p.estimated_cost_usd, reverse=True)
    suggestions = []
    for pl in all_pipelines[: cfg.analysis.top_pipelines_for_ai]:
        suggestions.extend(_rule_based_for_pipeline(pl, cfg))
    return suggestions


def _rule_based_for_pipeline(pipeline: PipelineRecord, cfg: AppConfig) -> List[OptimizationSuggestion]:
    results = []
    for act in pipeline.activities:
        tp = act.definition.get("typeProperties", {})
        if act.activity_type == "Copy":
            diu = int(tp.get("dataIntegrationUnits", 0))
            if diu >= 16:
                results.append(OptimizationSuggestion(
                    pipeline_name=pipeline.pipeline_name, factory_name=pipeline.factory_name,
                    environment=pipeline.environment, current_cost_usd=pipeline.estimated_cost_usd,
                    issue_category="High DIU Setting",
                    issue_description=f"'{act.activity_name}' uses {diu} DIUs — likely over-provisioned.",
                    suggestion=f"Remove explicit DIU or reduce from {diu} to 4-8. ADF auto-scales optimally. Test with 4 DIUs first.",
                    estimated_saving_pct=35.0, estimated_saving_usd=round(act.estimated_cost_usd * 0.35, 2),
                    priority="High", effort="Low",
                    optimized_code_snippet=json.dumps({"dataIntegrationUnits": 4, "parallelCopies": "auto"}, indent=2),
                ))
        if act.activity_type == "ExecuteDataFlow":
            cores = int(tp.get("compute", {}).get("coreCount", tp.get("coreCount", 8)))
            if cores >= 16:
                results.append(OptimizationSuggestion(
                    pipeline_name=pipeline.pipeline_name, factory_name=pipeline.factory_name,
                    environment=pipeline.environment, current_cost_usd=pipeline.estimated_cost_usd,
                    issue_category="Unoptimised Data Flow",
                    issue_description=f"Data Flow '{act.activity_name}' uses {cores} cores — high cost multiplier.",
                    suggestion=f"Reduce cores from {cores} to 8. Enable Quick Reuse IR. Add broadcast hints on small streams to eliminate shuffle.",
                    estimated_saving_pct=40.0, estimated_saving_usd=round(act.estimated_cost_usd * 0.40, 2),
                    priority="High", effort="Medium",
                    optimized_code_snippet=json.dumps({"compute": {"coreCount": 8, "computeType": "General"}, "traceLevel": "None"}, indent=2),
                ))

    has_watermark = any("watermark" in a.activity_name.lower() or a.activity_type == "Lookup" for a in pipeline.activities)
    has_copy = any(a.activity_type == "Copy" for a in pipeline.activities)
    if has_copy and not has_watermark and pipeline.run_count > 5:
        results.append(OptimizationSuggestion(
            pipeline_name=pipeline.pipeline_name, factory_name=pipeline.factory_name,
            environment=pipeline.environment, current_cost_usd=pipeline.estimated_cost_usd,
            issue_category="Full Load Instead of Delta",
            issue_description=f"Pipeline runs {pipeline.run_count}x with no watermark/delta pattern — likely full load each time.",
            suggestion="Implement incremental load: add Lookup for last watermark, filter source with UpdatedAt > watermark, update watermark after success.",
            estimated_saving_pct=50.0, estimated_saving_usd=round(pipeline.estimated_cost_usd * 0.50, 2),
            priority="High", effort="Medium",
            optimized_code_snippet=json.dumps({"sqlReaderQuery": {"value": "SELECT * FROM SourceTable WHERE UpdatedAt > '@{activity(\"LookupWatermark\").output.firstRow.Watermark}'", "type": "Expression"}}, indent=2),
        ))
    return results[:3]


def analyze_pipeline(pipeline: PipelineRecord, cfg: AppConfig) -> List[OptimizationSuggestion]:
    api_key = cfg.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("No ANTHROPIC_API_KEY — using rule-based suggestions for single pipeline")
        return _rule_based_for_pipeline(pipeline, cfg)
    return _analyze_pipeline(pipeline, cfg.analysis.date_range_days, cfg, api_key)


_PIPELINE_CODE_PROMPT = """You are a senior Azure Data Factory architect and cost optimization expert.

Analyze the pipeline JSON and produce a clear explanation of why this pipeline has high cost. Then provide an optimized pipeline definition or JSON fragment that reduces cost while preserving the pipeline's purpose.

Return the answer as plain text. The response should include:
- a short diagnosis of the cause of high cost
- actionable recommendations
- an optimized pipeline JSON snippet or code fragment
"""


def run_ai_code_generation(pipeline: PipelineRecord, cfg: AppConfig) -> str:
    api_key = cfg.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("No ANTHROPIC_API_KEY — using fallback code generation notice")
        return (
            "No Anthropic API key is configured. Use rule-based guidance to reduce cost:\n"
            "1) Lower excessive DIUs and compute cores.\n"
            "2) Move full loads to incremental loads with watermarking.\n"
            "3) Consolidate duplicate activities and reduce unnecessary data movement.\n"
        )

    act_lines = [f"  - {a.activity_name} [{a.activity_type}] | Cost: ${a.estimated_cost_usd:.2f} | Runs: {a.run_count}"
                 for a in pipeline.activities]
    description = pipeline.definition.get("properties", {}).get("description", "No description provided.")
    pl_json = json.dumps(pipeline.definition, indent=2)
    if len(pl_json) > 6000:
        pl_json = pl_json[:6000] + "\n...[truncated]"

    user_msg = _USER_TEMPLATE.format(
        pipeline_name=pipeline.pipeline_name, factory_name=pipeline.factory_name,
        environment=pipeline.environment, current_cost_usd=pipeline.estimated_cost_usd,
        days=cfg.analysis.date_range_days, run_count=pipeline.run_count,
        avg_duration_min=pipeline.avg_duration_sec / 60, description=description,
        pipeline_json=pl_json, activity_summary="\n".join(act_lines) or "  No activities.",
    )
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=cfg.genai.model, max_tokens=cfg.genai.max_tokens,
        system=_SYSTEM_PROMPT, messages=[{"role": "user", "content": _PIPELINE_CODE_PROMPT + "\n\n" + user_msg}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


# Compatibility alias for older imports
generate_suggestions = run_ai_optimization
