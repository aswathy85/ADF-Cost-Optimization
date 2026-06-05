"""mock_data.py — Generate realistic mock ADF data for local testing.

This module provides `generate_mock_data()` which fabricates factories,
pipelines, activities and triggers so you can run the tool without Azure
credentials. The generated objects match the `src.models` dataclasses.
"""
from __future__ import annotations
import json, random
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from src.models import ActivityRecord, FactoryRecord, PipelineRecord, ReportPayload, TriggerRecord

# A set of pipeline templates used to generate mock pipelines and activities
PIPELINE_TEMPLATES = [
    {
        "name": "pl_ingest_sales_daily",
        "activities": [
            {"name": "copy_sales_from_blob",     "type": "Copy",             "diu": 8,  "duration_min": 12},
            {"name": "transform_sales_dataflow", "type": "ExecuteDataFlow",  "diu": 16, "duration_min": 45},
            {"name": "upsert_sales_dwh",          "type": "Copy",             "diu": 4,  "duration_min": 8},
        ],
        "frequency_per_day": 1,
        "purpose": "Ingests daily sales CSV from Blob Storage, applies Mapping Data Flow transformations (16 DIUs), then upserts to Synapse DWH. Uses full load — no watermark.",
    },
    {
        "name": "pl_customer_360_refresh",
        "activities": [
            {"name": "lookup_last_watermark",  "type": "Lookup",                   "diu": 1,  "duration_min": 1},
            {"name": "copy_crm_delta",         "type": "Copy",                     "diu": 32, "duration_min": 60},
            {"name": "enrich_customer_ml",     "type": "AzureMLBatchExecution",    "diu": 0,  "duration_min": 120},
            {"name": "update_watermark",       "type": "SqlServerStoredProcedure", "diu": 0,  "duration_min": 1},
        ],
        "frequency_per_day": 0.5,
        "purpose": "Delta load from Salesforce CRM API (32 DIUs on Copy), runs ML churn scoring batch, updates high-watermark table.",
    },
    {
        "name": "pl_financial_close_monthly",
        "activities": [
            {"name": "validate_source_data", "type": "Lookup",           "diu": 1,  "duration_min": 2},
            {"name": "full_extract_gl",      "type": "Copy",             "diu": 64, "duration_min": 180},
            {"name": "reconcile_dataflow",   "type": "ExecuteDataFlow",  "diu": 32, "duration_min": 240},
            {"name": "generate_reports",     "type": "Copy",             "diu": 4,  "duration_min": 15},
            {"name": "notify_finance",       "type": "WebActivity",      "diu": 0,  "duration_min": 1},
        ],
        "frequency_per_day": 0.033,
        "purpose": "Monthly financial close: full GL extraction from SAP (64 DIUs), reconciliation Data Flow (32 DIUs), generates Excel reports.",
    },
    {
        "name": "pl_product_catalog_sync",
        "activities": [
            {"name": "copy_products_api",  "type": "Copy",            "diu": 4, "duration_min": 20},
            {"name": "flatten_json_df",    "type": "ExecuteDataFlow", "diu": 8, "duration_min": 15},
            {"name": "load_product_dim",   "type": "Copy",            "diu": 4, "duration_min": 5},
        ],
        "frequency_per_day": 4,
        "purpose": "Syncs product catalog from REST API to Azure SQL, flattens nested JSON in Data Flow, loads product dimension.",
    },
    {
        "name": "pl_log_aggregation_hourly",
        "activities": [
            {"name": "copy_app_logs",      "type": "Copy",            "diu": 8,  "duration_min": 8},
            {"name": "aggregate_logs_df",  "type": "ExecuteDataFlow", "diu": 16, "duration_min": 25},
            {"name": "archive_raw_logs",   "type": "Copy",            "diu": 4,  "duration_min": 5},
        ],
        "frequency_per_day": 24,
        "purpose": "Hourly log aggregation: copy app logs from Event Hubs, aggregate metrics in Data Flow, archive raw logs to cold storage.",
    },
    {
        "name": "pl_inventory_recon",
        "activities": [
            {"name": "copy_wms_inventory",    "type": "Copy",            "diu": 8,  "duration_min": 30},
            {"name": "copy_erp_inventory",    "type": "Copy",            "diu": 8,  "duration_min": 25},
            {"name": "reconcile_df",          "type": "ExecuteDataFlow", "diu": 16, "duration_min": 40},
            {"name": "send_discrepancy_email","type": "WebActivity",     "diu": 0,  "duration_min": 1},
        ],
        "frequency_per_day": 2,
        "purpose": "Reconciles WMS vs ERP inventory with parallel Copy activities, Data Flow reconciliation, emails discrepancy report.",
    },
    {
        "name": "pl_etl_reference_data",
        "activities": [
            {"name": "copy_country_codes",    "type": "Copy", "diu": 2, "duration_min": 2},
            {"name": "copy_currency_rates",   "type": "Copy", "diu": 2, "duration_min": 3},
            {"name": "copy_holiday_calendar", "type": "Copy", "diu": 2, "duration_min": 2},
        ],
        "frequency_per_day": 0.14,
        "purpose": "Weekly refresh of reference tables: country codes, currency exchange rates, holiday calendar from external APIs.",
    },
    {
        "name": "pl_user_activity_stream",
        "activities": [
            {"name": "copy_clickstream",    "type": "Copy",            "diu": 16, "duration_min": 45},
            {"name": "sessionize_df",       "type": "ExecuteDataFlow", "diu": 32, "duration_min": 90},
            {"name": "load_user_sessions",  "type": "Copy",            "diu": 8,  "duration_min": 20},
        ],
        "frequency_per_day": 1,
        "purpose": "Daily clickstream processing from ADLS, sessionization Data Flow (32 DIUs), loads user session data to Synapse.",
    },
    {
        "name": "pl_hr_employee_sync",
        "activities": [
            {"name": "copy_hr_source",    "type": "Copy",            "diu": 4, "duration_min": 10},
            {"name": "transform_hr_df",   "type": "ExecuteDataFlow", "diu": 8, "duration_min": 12},
            {"name": "load_employee_dim", "type": "Copy",            "diu": 2, "duration_min": 3},
        ],
        "frequency_per_day": 1,
        "purpose": "Daily HR employee data sync from Workday API to data warehouse employee dimension table.",
    },
    {
        "name": "pl_supplier_invoice_processing",
        "activities": [
            {"name": "copy_invoices_blob",   "type": "Copy",                     "diu": 8,  "duration_min": 20},
            {"name": "validate_invoices_df", "type": "ExecuteDataFlow",          "diu": 16, "duration_min": 30},
            {"name": "post_to_erp",          "type": "SqlServerStoredProcedure", "diu": 0,  "duration_min": 5},
            {"name": "archive_processed",    "type": "Copy",                     "diu": 4,  "duration_min": 8},
        ],
        "frequency_per_day": 3,
        "purpose": "Processes supplier invoice files from Blob, validates using Data Flow, posts approved invoices to ERP via stored procedure.",
    },
]

TRIGGER_TYPES = ["ScheduleTrigger", "TumblingWindowTrigger", "BlobEventsTrigger"]
# Naming templates by environment to produce realistic factory names
ENV_FACTORY_NAMES = {
    "dev":  ["adf-{company}-dev", "datafactory-dev-{dept}", "adf-dev-{dept}-01"],
    "qa":   ["adf-{company}-qa",  "datafactory-qa-{dept}",  "adf-qa-{dept}-01"],
    "uat":  ["adf-{company}-uat", "datafactory-uat-{dept}", "adf-uat-{dept}-01"],
    "prod": ["adf-{company}-prod","datafactory-prd-{dept}", "adf-{dept}-prd-01"],
}
COMPANIES    = ["contoso", "fabrikam", "northwind"]
DEPARTMENTS  = ["finance", "sales", "marketing", "logistics", "hr"]
# Cost assumptions used to estimate activity cost in the generator
COST_PER_DIU_HOUR = {
    "Copy": 0.25, "ExecuteDataFlow": 0.274, "AzureMLBatchExecution": 0.10,
    "Lookup": 0.005, "SqlServerStoredProcedure": 0.005, "WebActivity": 0.001,
    "ExecutePipeline": 0.001, "Wait": 0.001,
}
ACTIVITY_RUN_COST = 0.001

def generate_mock_data(seed: int = 42, days: int = 30) -> ReportPayload:
    """Generate a `ReportPayload` filled with mock factories, pipelines, activities and triggers.

    - `seed` ensures deterministic output for testing.
    - `days` controls the date range used to compute run counts and costs.
    """
    rng = random.Random(seed)
    company = rng.choice(COMPANIES)
    now = datetime.now(timezone.utc)
    factories: List[FactoryRecord] = []
    triggers: List[TriggerRecord] = []

    # Create a small set of factories per environment
    for env in ["dev", "qa", "uat", "prod"]:
        num_factories = rng.randint(2, 3)
        dept_pool = rng.sample(DEPARTMENTS, num_factories)
        for i in range(num_factories):
            dept = dept_pool[i]
            name_template = rng.choice(ENV_FACTORY_NAMES[env])
            factory_name = name_template.format(company=company, dept=dept)
            rg = f"rg-{dept}-{env}"
            num_pipelines = rng.randint(3, 6)
            pl_templates = rng.sample(PIPELINE_TEMPLATES, min(num_pipelines, len(PIPELINE_TEMPLATES)))
            factory_cost = 0.0
            pipeline_records: List[PipelineRecord] = []

            # Generate pipelines from templates and compute approximate costs
            for tpl in pl_templates:
                run_multiplier = {"dev": 0.4, "qa": 0.6, "uat": 0.8, "prod": 1.0}[env]
                total_runs = max(1, int(tpl["frequency_per_day"] * days * run_multiplier * rng.uniform(0.8, 1.2)))
                pipeline_cost = 0.0
                total_duration_sec = 0.0
                activity_records: List[ActivityRecord] = []

                for act_tpl in tpl["activities"]:
                    act_type = act_tpl["type"]
                    diu = act_tpl["diu"]
                    avg_dur_sec = act_tpl["duration_min"] * 60 * rng.uniform(0.9, 1.3)
                    diu_hours = diu * (avg_dur_sec / 3600) * total_runs
                    act_cost = diu_hours * COST_PER_DIU_HOUR.get(act_type, 0.01) + total_runs * ACTIVITY_RUN_COST
                    pipeline_cost += act_cost
                    total_duration_sec += avg_dur_sec * total_runs
                    activity_records.append(ActivityRecord(
                        activity_name=act_tpl["name"], activity_type=act_type,
                        pipeline_name=tpl["name"], factory_name=factory_name,
                        environment=env, subscription_id="sub-mock-001",
                        run_count=total_runs, total_duration_sec=avg_dur_sec * total_runs,
                        diu_hours=diu_hours, estimated_cost_usd=round(act_cost, 4),
                        avg_duration_sec=avg_dur_sec,
                        definition={"name": act_tpl["name"], "type": act_type,
                                    "typeProperties": {"dataIntegrationUnits": diu, "coreCount": diu}},
                    ))

                # Accumulate pipeline and factory level stats
                factory_cost += pipeline_cost
                cost_tier = "high" if pipeline_cost >= 200 else "medium" if pipeline_cost >= 50 else "low"
                last_run = now - timedelta(hours=rng.randint(1, 48))
                run_costs = []
                for run_index in range(min(total_runs, 8)):
                    duration_ms = int(avg_dur_sec * 1000 * rng.uniform(0.9, 1.1))
                    run_costs.append({
                        "run_id": f"mock-run-{tpl['name']}-{run_index+1}",
                        "status": rng.choice(["Succeeded", "Failed"] if rng.random() < 0.1 else ["Succeeded"]),
                        "run_start": now - timedelta(hours=run_index * 6 + rng.randint(1, 12)),
                        "run_end": now - timedelta(hours=run_index * 6 - 1 + rng.randint(1, 12)),
                        "duration_ms": duration_ms,
                        "estimated_cost_usd": round((pipeline_cost / max(total_runs, 1)) * rng.uniform(0.9, 1.1), 4),
                    })
                pl_record = PipelineRecord(
                    pipeline_name=tpl["name"], factory_name=factory_name, environment=env,
                    subscription_id="sub-mock-001", resource_group=rg,
                    run_count=total_runs, total_duration_sec=total_duration_sec,
                    estimated_cost_usd=round(pipeline_cost, 4),
                    avg_cost_per_run=round(pipeline_cost / max(total_runs, 1), 4),
                    avg_duration_sec=total_duration_sec / max(total_runs, 1),
                    last_run_end=last_run, cost_tier=cost_tier,
                    activities=activity_records,
                    run_costs=run_costs,
                    definition=_build_definition(tpl),
                )
                pipeline_records.append(pl_record)

            # Generate triggers for the factory
            num_triggers = rng.randint(2, 5)
            factory_triggers = []
            for t_idx in range(num_triggers):
                t_type = rng.choice(TRIGGER_TYPES)
                t_enabled = rng.random() < {"dev": 0.3, "qa": 0.5, "uat": 0.7, "prod": 0.95}[env]
                schedule = {"ScheduleTrigger": rng.choice(["Every 1 Hour","Every 24 Hour","Every 6 Hour","Every 1 Day"]),
                            "TumblingWindowTrigger": rng.choice(["Tumbling: 1 Hour","Tumbling: 15 Minute"]),
                            "BlobEventsTrigger": "Event-driven (Blob)"}.get(t_type, "")
                t_pl = [rng.choice(pl_templates)["name"]] if pl_templates else []
                tr = TriggerRecord(
                    trigger_name=f"tr_{t_type[:3].lower()}_{dept}_{t_idx+1:02d}",
                    factory_name=factory_name, environment=env,
                    subscription_id="sub-mock-001", resource_group=rg,
                    trigger_type=t_type, status="Started" if t_enabled else "Stopped",
                    is_enabled=t_enabled, schedule_expression=schedule,
                    pipelines_triggered=t_pl,
                    last_triggered=now - timedelta(hours=rng.randint(0, 72)) if t_enabled else None,
                )
                factory_triggers.append(tr)
                triggers.append(tr)

            factories.append(FactoryRecord(
                factory_name=factory_name,
                factory_id=f"/subscriptions/sub-mock-001/resourceGroups/{rg}/providers/Microsoft.DataFactory/factories/{factory_name}",
                resource_group=rg, subscription_id="sub-mock-001",
                location="eastus", environment=env,
                estimated_cost_usd=round(factory_cost, 4),
                pipeline_count=len(pipeline_records),
                trigger_count=num_triggers,
                enabled_trigger_count=sum(1 for t in factory_triggers if t.is_enabled),
                pipelines=pipeline_records,
            ))

    # Final payload aggregation: totals by environment + overall
    total = sum(f.estimated_cost_usd for f in factories)
    env_costs = {}
    for f in factories:
        env_costs[f.environment] = env_costs.get(f.environment, 0) + f.estimated_cost_usd
    return ReportPayload(
        generated_at=now, date_range_days=days, factories=factories, triggers=triggers,
        total_cost_usd=round(total, 4),
        cost_by_environment={k: round(v, 4) for k, v in env_costs.items()},
        cost_by_factory={f.factory_name: round(f.estimated_cost_usd, 4) for f in factories},
    )

def _build_definition(tpl):
    activities = []
    for act in tpl["activities"]:
        tp = {}
        if act["type"] == "Copy":
            tp = {"source": {"type": "DelimitedTextSource"}, "sink": {"type": "AzureSqlSink", "writeBehavior": "insert"},
                  "enableStaging": False, "parallelCopies": 1, "dataIntegrationUnits": act["diu"]}
        elif act["type"] == "ExecuteDataFlow":
            tp = {"dataflow": {"referenceName": f"df_{act['name']}", "type": "DataFlowReference"},
                  "compute": {"coreCount": act["diu"], "computeType": "General"},
                  "integrationRuntime": {"referenceName": "AutoResolveIntegrationRuntime", "type": "IntegrationRuntimeReference"}}
        elif act["type"] == "Lookup":
            tp = {"source": {"type": "AzureSqlSource", "sqlReaderQuery": "SELECT MAX(UpdatedAt) as Watermark FROM dbo.WatermarkTable"},
                  "firstRowOnly": True}
        activities.append({"name": act["name"], "type": act["type"], "typeProperties": tp, "dependsOn": []})
    return {"name": tpl["name"], "properties": {"activities": activities, "description": tpl["purpose"], "concurrency": 1}}
