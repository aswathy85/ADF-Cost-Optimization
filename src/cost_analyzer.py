"""cost_analyzer.py — Build the ReportPayload from Azure API responses.

This module orchestrates calling the `azure_client` helpers, estimating
activity-level costs when run metrics are available, and assembling the
hierarchical payload consumed by the report generator and GenAI modules.
"""
from __future__ import annotations
import calendar
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List
from src.config import AppConfig
from src.models import ActivityRecord, FactoryRecord, PipelineRecord, ReportPayload, TriggerRecord
from src import azure_client

logger = logging.getLogger(__name__)

_COST_PER_DIU_HOUR = {
    "Copy": 0.25, "ExecuteDataFlow": 0.274, "AzureMLBatchExecution": 0.10,
    "DatabricksNotebook": 0.70, "DatabricksSparkPython": 0.70,
    "HDInsightHive": 0.50, "HDInsightSpark": 0.50,
    "Lookup": 0.005, "SqlServerStoredProcedure": 0.005,
    "WebActivity": 0.001, "ExecutePipeline": 0.001, "Wait": 0.001,
    "GetMetadata": 0.001, "ForEach": 0.001, "IfCondition": 0.001,
}
_ACTIVITY_RUN_COST = 0.001

def detect_environment(factory_name: str, cfg: AppConfig) -> str:
    """Map factory name to one of configured environments using patterns."""
    name_lower = factory_name.lower()
    for env_name, env_cfg in cfg.analysis.environments.items():
        for pattern in env_cfg.patterns:
            if pattern.lower() in name_lower:
                return env_name
    return "prod"

def assign_cost_tier(cost_usd: float, cfg: AppConfig) -> str:
    """Classify a numeric cost into a human-friendly tier (high/medium/low)."""
    if cost_usd >= cfg.cost_thresholds.high:   return "high"
    if cost_usd >= cfg.cost_thresholds.medium: return "medium"
    return "low"

def build_report_payload(cfg: AppConfig) -> ReportPayload:
    """Main entrypoint: scan subscriptions, collect factory/pipeline/trigger data.

    This method attempts to use Cost Management totals when available and
    otherwise falls back to pipeline-level estimates computed from activity
    definitions and pipeline run metrics.
    """
    now = datetime.now(timezone.utc)
    days = cfg.analysis.date_range_days
    start_date = getattr(cfg.analysis, "start_date", None)
    end_date = getattr(cfg.analysis, "end_date", None)
    all_factories: List[FactoryRecord] = []
    all_triggers: List[TriggerRecord] = []
    cost_by_factory: Dict[str, float] = {}
    cost_history_by_month: Dict[str, float] = {}

    for sub_id in cfg.azure.subscription_ids:
        logger.info("Scanning subscription: %s", sub_id)
        try:
            for rec in azure_client.get_adf_costs(sub_id, days, cfg.azure.resource_groups, start_date, end_date):
                fn = rec["factory_name"].lower()
                cost_by_factory[fn] = cost_by_factory.get(fn, 0) + rec["cost_usd"]
        except Exception as exc:
            logger.warning("Cost Management API unavailable: %s", exc)

        try:
            for hist in azure_client.get_adf_cost_history(sub_id, days, cfg.azure.resource_groups, start_date, end_date):
                period = hist.get("period") or ""
                cost_history_by_month[period] = cost_history_by_month.get(period, 0) + hist.get("cost_usd", 0)
        except Exception as exc:
            logger.warning("Cost history unavailable: %s", exc)

        try:
            factory_list = azure_client.list_factories(sub_id, cfg.azure.resource_groups)
            logger.info("Found %d ADF factory(s) in subscription %s for resource groups %s",
                        len(factory_list), sub_id, cfg.azure.resource_groups or "ALL")
        except Exception as exc:
            logger.error("Cannot list factories: %s", exc)
            continue

        for fdata in factory_list:
            factory_name = fdata["name"]
            env = detect_environment(factory_name, cfg)
            rg  = fdata["resource_group"]
            pipeline_records: List[PipelineRecord] = []

            try:
                pipelines = azure_client.list_pipelines(sub_id, rg, factory_name)
                logger.info("Factory %s: found %d pipeline definition(s)", factory_name, len(pipelines))
            except Exception as exc:
                logger.warning("Cannot list pipelines for %s: %s", factory_name, exc)
                pipelines = []

            runs_by_pipeline: Dict[str, List[Dict]] = {}
            try:
                for r in azure_client.get_pipeline_runs(sub_id, rg, factory_name, days, start_date, end_date):
                    runs_by_pipeline.setdefault(r["pipeline_name"], []).append(r)
                logger.info("Factory %s: found %d pipeline run(s) in selected date range",
                            factory_name, sum(len(v) for v in runs_by_pipeline.values()))
            except Exception as exc:
                logger.debug("Cannot get pipeline runs for %s: %s", factory_name, exc)

            pipeline_runs_map: Dict[str, List[Dict]] = {}
            for pl in pipelines:
                pl_name = pl["name"]
                pl_runs = runs_by_pipeline.get(pl_name, [])
                pipeline_runs_map[pl_name] = pl_runs
                run_count = len(pl_runs)
                failed_run_count = sum(1 for r in pl_runs if str(r.get("status", "")).lower() == "failed")
                total_dur_sec = sum(r.get("duration_ms", 0) / 1000 for r in pl_runs)
                activity_runs = []
                try:
                    activity_runs = azure_client.get_activity_runs(sub_id, rg, factory_name, pl_name, days, start_date, end_date)
                except Exception as exc:
                    logger.debug("Cannot get activity runs for %s.%s: %s", factory_name, pl_name, exc)
                act_records, pl_cost = _estimate_activity_costs(
                    pl.get("activities", []), pl_runs, activity_runs, factory_name, pl_name, env, sub_id, cfg)
                estimated_pl_cost = round(pl_cost, 4)
                run_costs = _estimate_pipeline_run_costs(pl_runs, estimated_pl_cost)
                ends = [r["run_end"] for r in pl_runs if r.get("run_end")]
                last_run = max(ends) if ends else None
                last_status = ""
                if pl_runs:
                    latest_run = max(pl_runs, key=lambda r: r.get("run_end") or r.get("run_start") or datetime.min.replace(tzinfo=timezone.utc))
                    last_status = latest_run.get("status", "")
                pipeline_records.append(PipelineRecord(
                    pipeline_name=pl_name, factory_name=factory_name, environment=env,
                    subscription_id=sub_id, resource_group=rg, run_count=run_count,
                    total_duration_sec=total_dur_sec, estimated_cost_usd=estimated_pl_cost,
                    actual_cost_usd=0.0,
                    avg_cost_per_run=round(estimated_pl_cost / max(run_count, 1), 4),
                    actual_avg_cost_per_run=0.0,
                    avg_duration_sec=total_dur_sec / max(run_count, 1),
                    last_run_end=last_run, failed_run_count=failed_run_count,
                    last_run_status=last_status, cost_tier=assign_cost_tier(estimated_pl_cost, cfg),
                    activities=act_records, run_costs=run_costs, definition=pl.get("definition", {}),
                ))
            factory_cost = cost_by_factory.get(factory_name.lower())
            if factory_cost is None:
                factory_cost = sum(p.estimated_cost_usd for p in pipeline_records)
                for p in pipeline_records:
                    p.actual_cost_usd = p.estimated_cost_usd
                    p.actual_avg_cost_per_run = round(p.actual_cost_usd / max(p.run_count, 1), 4)
            else:
                logger.debug("Using Cost Management actual cost for factory %s: %s", factory_name, factory_cost)
                total_factory_seconds = sum(p.total_duration_sec for p in pipeline_records)
                total_estimated = sum(p.estimated_cost_usd for p in pipeline_records)
                for p in pipeline_records:
                    if total_factory_seconds > 0:
                        p.actual_cost_usd = round(factory_cost * (p.total_duration_sec / total_factory_seconds), 4)
                    elif total_estimated > 0:
                        p.actual_cost_usd = round(factory_cost * (p.estimated_cost_usd / total_estimated), 4)
                    else:
                        p.actual_cost_usd = round(factory_cost / max(len(pipeline_records), 1), 4)
                    p.actual_avg_cost_per_run = round(p.actual_cost_usd / max(p.run_count, 1), 4)
                    p.cost_tier = assign_cost_tier(p.actual_cost_usd, cfg)
            for p in pipeline_records:
                p.run_costs = _estimate_pipeline_run_costs(
                    pipeline_runs_map.get(p.pipeline_name, []), p.estimated_cost_usd, p.actual_cost_usd)
                _apply_actual_activity_costs(p.activities, p.actual_cost_usd, p.estimated_cost_usd)

            factory_cost = cost_by_factory.get(factory_name.lower())
            if factory_cost is None:
                factory_cost = sum(p.estimated_cost_usd for p in pipeline_records)
            else:
                logger.debug("Using Cost Management actual cost for factory %s: %s", factory_name, factory_cost)
            factory_triggers: List[TriggerRecord] = []
            try:
                for t in azure_client.list_triggers(sub_id, rg, factory_name):
                    tr = TriggerRecord(
                        trigger_name=t["name"], factory_name=factory_name, environment=env,
                        subscription_id=sub_id, resource_group=rg, trigger_type=t["type"],
                        status=t["runtime_state"], is_enabled=t["is_enabled"],
                        schedule_expression=t["schedule_expression"], pipelines_triggered=t["pipelines"],
                    )
                    factory_triggers.append(tr)
                    all_triggers.append(tr)
            except Exception as exc:
                logger.warning("Cannot list triggers for %s: %s", factory_name, exc)

            all_factories.append(FactoryRecord(
                factory_name=factory_name, factory_id=fdata["id"],
                resource_group=rg, subscription_id=sub_id, location=fdata["location"],
                environment=env, estimated_cost_usd=round(factory_cost, 4),
                pipeline_count=len(pipeline_records), trigger_count=len(factory_triggers),
                enabled_trigger_count=sum(1 for t in factory_triggers if t.is_enabled),
                pipelines=pipeline_records,
            ))

    total_cost = sum(f.estimated_cost_usd for f in all_factories)
    env_costs: Dict[str, float] = {}
    for f in all_factories:
        env_costs[f.environment] = round(env_costs.get(f.environment, 0) + f.estimated_cost_usd, 4)

    forecast_months, monthly_average, six_month_total = _build_forecast(
        cost_history_by_month, total_cost, days, end_date or now
    )
    return ReportPayload(
        generated_at=now, date_range_days=days, factories=all_factories, triggers=all_triggers,
        total_cost_usd=round(total_cost, 4), cost_by_environment=env_costs,
        cost_by_factory={f.factory_name: round(f.estimated_cost_usd, 4) for f in all_factories},
        analysis_start_date=getattr(cfg.analysis, "start_date", None),
        analysis_end_date=getattr(cfg.analysis, "end_date", None),
        forecast_months=forecast_months,
        forecast_monthly_average_usd=monthly_average,
        forecast_total_6_months_usd=six_month_total,
    )

def _group_activity_runs_by_name(activity_runs: List[Dict]) -> Dict[str, List[Dict]]:
    grouped: Dict[str, List[Dict]] = {}
    for run in activity_runs:
        name = run.get("activity_name", "unknown")
        grouped.setdefault(name, []).append(run)
    return grouped


def _summarize_activity_run_details(activity_runs: List[Dict]) -> Dict[str, object]:
    summary = {"activity_run_count": len(activity_runs)}
    total_bytes = 0
    total_rows = 0
    for run in activity_runs:
        output = run.get("output")
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except ValueError:
                output = None
        if isinstance(output, dict):
            for key in ("bytesRead", "BytesRead", "bytesWritten", "rowsRead", "rowsCopied", "rowsWritten"):
                if key in output and isinstance(output[key], (int, float)):
                    total_bytes += output[key]
            rows = output.get("rowsRead") or output.get("rowsCopied") or output.get("rowsWritten")
            if isinstance(rows, (int, float)):
                total_rows += rows
    if total_bytes:
        summary["bytes_processed"] = total_bytes
    if total_rows:
        summary["rows_processed"] = total_rows
    if activity_runs:
        statuses = {}
        for run in activity_runs:
            statuses[run.get("status", "unknown")] = statuses.get(run.get("status", "unknown"), 0) + 1
        summary["run_status_counts"] = statuses
        summary["latest_run_start"] = activity_runs[-1].get("run_start")
        summary["latest_run_end"] = activity_runs[-1].get("run_end")
        summary["sample_output"] = activity_runs[0].get("output")
    return summary


def _apply_actual_activity_costs(activities: List[ActivityRecord], actual_pipeline_cost: float, estimated_pipeline_cost: float):
    if not activities:
        return
    total_activity_seconds = sum(a.total_duration_sec for a in activities)
    total_estimated = sum(a.estimated_cost_usd for a in activities)
    for activity in activities:
        if actual_pipeline_cost is not None:
            if total_activity_seconds > 0:
                activity.actual_cost_usd = round(actual_pipeline_cost * (activity.total_duration_sec / total_activity_seconds), 4)
            elif total_estimated > 0:
                activity.actual_cost_usd = round(actual_pipeline_cost * (activity.estimated_cost_usd / total_estimated), 4)
            else:
                activity.actual_cost_usd = round(actual_pipeline_cost / max(len(activities), 1), 4)
        else:
            activity.actual_cost_usd = activity.estimated_cost_usd
        activity.actual_avg_cost_per_run = round(activity.actual_cost_usd / max(activity.run_count, 1), 4)


def _estimate_activity_costs(activity_defs, runs, activity_runs, factory_name, pipeline_name, env, sub_id, cfg):
    run_count = len(runs)
    avg_pipeline_sec = sum(r.get("duration_ms", 0) / 1000 for r in runs) / max(run_count, 1)
    activity_runs_by_name = _group_activity_runs_by_name(activity_runs)
    records, pipeline_cost = [], 0.0
    weights = {"Copy": 0.30, "ExecuteDataFlow": 0.50, "AzureMLBatchExecution": 0.60,
               "DatabricksNotebook": 0.55, "Lookup": 0.02, "SqlServerStoredProcedure": 0.05,
               "WebActivity": 0.02, "ExecutePipeline": 0.01, "Wait": 0.05}
    defined_activity_names = {act.get("name", "unknown") for act in activity_defs}
    for act in activity_defs:
        act_name = act.get("name", "unknown")
        act_type = act.get("type", "Copy")
        tp = act.get("typeProperties", {})
        diu = int(tp.get("dataIntegrationUnits", tp.get("coreCount", 4)))
        activity_runs_for_act = activity_runs_by_name.get(act_name, [])
        if activity_runs_for_act:
            total_act_sec = sum(r.get("duration_ms", 0) / 1000 for r in activity_runs_for_act)
            run_count_for_act = len(activity_runs_for_act)
            run_activity_type = activity_runs_for_act[0].get("activity_type", act_type)
        else:
            total_act_sec = avg_pipeline_sec * weights.get(act_type, 0.10) * run_count
            run_count_for_act = run_count
            run_activity_type = act_type
        diu_hours = diu * (total_act_sec / 3600)
        act_cost = diu_hours * _COST_PER_DIU_HOUR.get(run_activity_type, _COST_PER_DIU_HOUR.get(act_type, 0.01)) + run_count_for_act * _ACTIVITY_RUN_COST
        pipeline_cost += act_cost
        records.append(ActivityRecord(
            activity_name=act_name, activity_type=run_activity_type,
            pipeline_name=pipeline_name, factory_name=factory_name,
            environment=env, subscription_id=sub_id, run_count=run_count_for_act,
            total_duration_sec=total_act_sec, diu_hours=round(diu_hours, 4),
            estimated_cost_usd=round(act_cost, 4), actual_cost_usd=0.0,
            avg_cost_per_run=round(act_cost / max(run_count_for_act, 1), 4),
            actual_avg_cost_per_run=0.0,
            compute_hours=round(diu_hours, 4),
            data_details=_summarize_activity_run_details(activity_runs_for_act) if activity_runs_for_act else {},
            activity_runs=activity_runs_for_act,
            avg_duration_sec=total_act_sec / max(run_count_for_act, 1), definition=act,
        ))

    # Add any activity runs that do not correspond to definition names
    for run_name, run_list in activity_runs_by_name.items():
        if run_name in defined_activity_names:
            continue
        total_act_sec = sum(r.get("duration_ms", 0) / 1000 for r in run_list)
        run_count_for_act = len(run_list)
        run_activity_type = run_list[0].get("activity_type", "Unknown")
        diu_hours = max(0.0, total_act_sec / 3600)
        act_cost = diu_hours * _COST_PER_DIU_HOUR.get(run_activity_type, 0.01) + run_count_for_act * _ACTIVITY_RUN_COST
        pipeline_cost += act_cost
        records.append(ActivityRecord(
            activity_name=run_name,
            activity_type=run_activity_type,
            pipeline_name=pipeline_name, factory_name=factory_name,
            environment=env, subscription_id=sub_id, run_count=run_count_for_act,
            total_duration_sec=total_act_sec, diu_hours=round(diu_hours, 4),
            estimated_cost_usd=round(act_cost, 4), actual_cost_usd=0.0,
            avg_cost_per_run=round(act_cost / max(run_count_for_act, 1), 4),
            actual_avg_cost_per_run=0.0,
            compute_hours=round(diu_hours, 4),
            data_details=_summarize_activity_run_details(run_list),
            activity_runs=run_list,
            avg_duration_sec=total_act_sec / max(run_count_for_act, 1), definition={},
        ))
    return records, pipeline_cost

def _estimate_pipeline_run_costs(runs: List[Dict], estimated_pipeline_cost: float, actual_pipeline_cost: float | None = None) -> List[Dict]:
    if not runs:
        return [{
            "run_id": "N/A",
            "status": "No runs",
            "run_start": None,
            "run_end": None,
            "duration_ms": 0,
            "estimated_cost_usd": round(estimated_pipeline_cost, 4),
            "actual_cost_usd": round(actual_pipeline_cost if actual_pipeline_cost is not None else estimated_pipeline_cost, 4),
        }]
    total_duration = sum(max(float(r.get("duration_ms", 0) or 0), 0) for r in runs)
    equal_est_cost = estimated_pipeline_cost / max(len(runs), 1)
    equal_act_cost = (actual_pipeline_cost / max(len(runs), 1)) if actual_pipeline_cost is not None else equal_est_cost
    results = []
    for run in runs:
        duration_ms = max(float(run.get("duration_ms", 0) or 0), 0)
        if total_duration > 0:
            est_cost = estimated_pipeline_cost * duration_ms / total_duration
            act_cost = (actual_pipeline_cost * duration_ms / total_duration) if actual_pipeline_cost is not None else est_cost
        else:
            est_cost = equal_est_cost
            act_cost = equal_act_cost
        results.append({
            "run_id": run.get("run_id", ""),
            "status": run.get("status", ""),
            "run_start": run.get("run_start"),
            "run_end": run.get("run_end"),
            "duration_ms": duration_ms,
            "estimated_cost_usd": round(est_cost, 4),
            "actual_cost_usd": round(act_cost, 4),
        })
    return results


def _add_months(dt: datetime, months: int) -> datetime:
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _build_forecast(cost_history_by_month: Dict[str, float], total_cost: float, days: int, end_date: datetime):
    monthly_average = 0.0
    if cost_history_by_month:
        monthly_values = sorted(
            (value for value in cost_history_by_month.values()), reverse=False
        )
        monthly_average = round(sum(monthly_values) / max(len(monthly_values), 1), 2)
    else:
        monthly_average = round(total_cost / max(days, 1) * 30.4375, 2)

    forecast = [{
        "label": "Selected Range",
        "actual_cost_usd": round(total_cost, 2),
        "estimated_cost_usd": None,
    }]
    for i in range(1, 7):
        month_label = _add_months(end_date, i).strftime("%b %Y")
        forecast.append({
            "label": month_label,
            "actual_cost_usd": None,
            "estimated_cost_usd": monthly_average,
        })
    return forecast, monthly_average, round(monthly_average * 6, 2)
