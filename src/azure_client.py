"""azure_client.py — Azure SDK wrappers for ADF and Cost Management APIs.

Contains small helper functions that encapsulate Azure SDK calls. These helpers
return plain Python dictionaries so the rest of the tool can remain SDK-agnostic
and easy to test with `mock_data.py`.
"""
from __future__ import annotations
import logging, os
from datetime import datetime, timedelta, timezone
from typing import Dict, List
logger = logging.getLogger(__name__)

def _is_configured_secret(value: str | None) -> bool:
    """Return True when a credential value looks intentionally configured."""
    if not value:
        return False
    normalized = value.strip().lower()
    return normalized not in {
        "",
        "your-tenant-id",
        "your-client-id",
        "your-client-secret",
        "your-subscription-id",
        "your-subscription-id-1",
        "your-subscription-id-2",
        "<tenant-id>",
        "<client-id>",
        "<client-secret>",
    }

def _get_credential():
    """Return an Azure credential instance.

    Prefer explicit client secret credentials when environment variables are
    set (useful for CI), otherwise fall back to DefaultAzureCredential which
    supports developer sign-in and managed identities.
    """
    from azure.identity import (
        AzureCliCredential,
        AzureDeveloperCliCredential,
        AzurePowerShellCredential,
        ChainedTokenCredential,
        ClientSecretCredential,
        InteractiveBrowserCredential,
        SharedTokenCacheCredential,
    )
    cid = os.environ.get("AZURE_CLIENT_ID")
    cs  = os.environ.get("AZURE_CLIENT_SECRET")
    tid = os.environ.get("AZURE_TENANT_ID")
    if all(_is_configured_secret(v) for v in (cid, cs, tid)):
        logger.info("Using ClientSecretCredential (Service Principal)")
        return ClientSecretCredential(tid, cid, cs)
    logger.info("Using interactive/developer Azure credential chain")
    return ChainedTokenCredential(
        AzureCliCredential(),
        AzurePowerShellCredential(),
        AzureDeveloperCliCredential(),
        SharedTokenCacheCredential(),
        InteractiveBrowserCredential(),
    )

def list_subscriptions() -> List[Dict]:
    """List subscriptions available to the authenticated Azure identity."""
    import requests
    cred = _get_credential()
    token = cred.get_token("https://management.azure.com/.default").token
    url = "https://management.azure.com/subscriptions?api-version=2022-12-01"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    resp.raise_for_status()

    subscriptions = []
    for sub in resp.json().get("value", []):
        subscriptions.append({
            "id": sub.get("subscriptionId", ""),
            "name": sub.get("displayName") or sub.get("subscriptionId", ""),
        })
    return subscriptions

def list_resource_groups(subscription_id: str) -> List[str]:
    """List resource group names in a subscription."""
    from azure.mgmt.resource import ResourceManagementClient

    cred = _get_credential()
    client = ResourceManagementClient(cred, subscription_id)
    return [rg.name for rg in client.resource_groups.list()]

def list_factories(subscription_id: str, resource_groups: List[str] = None) -> List[Dict]:
    # List ADF factories in the subscription, with optional resource group filter
    from azure.mgmt.datafactory import DataFactoryManagementClient
    cred = _get_credential()
    client = DataFactoryManagementClient(cred, subscription_id)
    factories = []
    try:
        for factory in client.factories.list():
            rg = _extract_rg(factory.id)
            if resource_groups and rg not in resource_groups:
                continue
            factories.append({"name": factory.name, "id": factory.id, "resource_group": rg,
                               "location": factory.location, "subscription_id": subscription_id})
    except Exception as exc:
        logger.error("Error listing factories in %s: %s", subscription_id, exc)
    return factories

def list_pipelines(subscription_id: str, resource_group: str, factory_name: str) -> List[Dict]:
    # Return a list of pipeline dicts for the given factory
    from azure.mgmt.datafactory import DataFactoryManagementClient
    cred = _get_credential()
    client = DataFactoryManagementClient(cred, subscription_id)
    pipelines = []
    try:
        for pl in client.pipelines.list_by_factory(resource_group, factory_name):
            raw = pl.as_dict() if hasattr(pl, "as_dict") else {}
            pipelines.append({"name": pl.name,
                               "activities": raw.get("properties", {}).get("activities", []),
                               "definition": raw})
    except Exception as exc:
        logger.error("Error listing pipelines for %s: %s", factory_name, exc)
    return pipelines

def get_pipeline_runs(subscription_id: str, resource_group: str, factory_name: str, days: int = 30, start_date=None, end_date=None) -> List[Dict]:
    # Query recent pipeline runs for the factory using a time-filter
    from azure.mgmt.datafactory import DataFactoryManagementClient
    from azure.mgmt.datafactory.models import RunFilterParameters
    cred = _get_credential()
    client = DataFactoryManagementClient(cred, subscription_id)
    now = datetime.now(timezone.utc)
    start = start_date or (now - timedelta(days=days))
    end = end_date or now
    runs = []
    try:
        fp = RunFilterParameters(last_updated_after=start, last_updated_before=end)
        for run in client.pipeline_runs.query_by_factory(resource_group, factory_name, fp).value:
            runs.append({"run_id": run.run_id, "pipeline_name": run.pipeline_name,
                         "status": run.status, "duration_ms": run.duration_in_ms or 0,
                         "run_start": run.run_start, "run_end": run.run_end})
    except Exception as exc:
        logger.debug("Error getting pipeline runs for %s: %s", factory_name, exc)
    return runs


def get_activity_runs(subscription_id: str, resource_group: str, factory_name: str, pipeline_name: str, days: int = 30, start_date=None, end_date=None) -> List[Dict]:
    """Query activity run details for a specific pipeline within the selected time range."""
    from azure.mgmt.datafactory import DataFactoryManagementClient
    from azure.mgmt.datafactory.models import RunFilterParameters
    cred = _get_credential()
    client = DataFactoryManagementClient(cred, subscription_id)
    now = datetime.now(timezone.utc)
    start = _normalize_datetime(start_date) or (now - timedelta(days=days))
    end = _normalize_datetime(end_date) or now
    activity_runs = []
    try:
        fp = RunFilterParameters(last_updated_after=start, last_updated_before=end)
        query_fn = getattr(client.activity_runs, 'query_by_pipeline', None)
        if query_fn is not None:
            run_iter = query_fn(resource_group, factory_name, pipeline_name, fp).value
        else:
            logger.debug("query_by_pipeline unavailable; falling back to query_by_factory for activity runs")
            run_iter = (r for r in client.activity_runs.query_by_factory(resource_group, factory_name, fp).value
                        if getattr(r, 'pipeline_name', '') == pipeline_name)
        for run in run_iter:
            run_start = getattr(run, "activity_run_start", None) or getattr(run, "run_start", None)
            run_end = getattr(run, "activity_run_end", None) or getattr(run, "run_end", None)
            activity_runs.append({
                "activity_run_id": getattr(run, "activity_run_id", ""),
                "activity_name": getattr(run, "activity_name", ""),
                "activity_type": getattr(run, "activity_type", ""),
                "pipeline_name": getattr(run, "pipeline_name", ""),
                "status": getattr(run, "status", ""),
                "duration_ms": getattr(run, "duration_in_ms", 0) or 0,
                "run_start": run_start,
                "run_end": run_end,
                "input": getattr(run, "input", None),
                "output": getattr(run, "output", None),
            })
    except Exception as exc:
        logger.debug("Error getting activity runs for %s/%s: %s", factory_name, pipeline_name, exc)
    return activity_runs


def list_triggers(subscription_id: str, resource_group: str, factory_name: str) -> List[Dict]:
    # Gather trigger metadata and normalize to simple dict format
    from azure.mgmt.datafactory import DataFactoryManagementClient
    cred = _get_credential()
    client = DataFactoryManagementClient(cred, subscription_id)
    triggers = []
    try:
        for trigger in client.triggers.list_by_factory(resource_group, factory_name):
            raw = trigger.as_dict() if hasattr(trigger, "as_dict") else {}
            props = raw.get("properties", {}) if isinstance(raw, dict) else {}
            rt_state = (props.get("runtimeState") or props.get("runtime_state")
                        or getattr(trigger, "runtime_state", None)
                        or getattr(trigger, "runtimeState", None)
                        or props.get("status")
                        or raw.get("status")
                        or "Stopped")
            rt_state = str(rt_state).strip()
            normalized = rt_state.lower()
            if normalized == "started":
                rt_state = "Started"
            elif normalized == "stopped":
                rt_state = "Stopped"
            elif normalized == "disabled":
                rt_state = "Disabled"
            ttype = props.get("type", "")
            schedule_expr = ""
            if ttype == "ScheduleTrigger":
                rec = props.get("recurrence", {})
                schedule_expr = f"Every {rec.get('interval','')} {rec.get('frequency','')}"
            elif ttype == "TumblingWindowTrigger":
                schedule_expr = f"Tumbling: {props.get('interval','')} {props.get('frequency','')}"
            elif "BlobEvents" in ttype:
                schedule_expr = "Event-driven (Blob)"
            pipeline_refs = [p.get("pipelineReference", {}).get("referenceName", "")
                             for p in props.get("pipelines", [])]
            triggers.append({"name": trigger.name, "type": ttype, "runtime_state": rt_state,
                              "is_enabled": normalized == "started", "schedule_expression": schedule_expr,
                              "pipelines": [p for p in pipeline_refs if p],
                              "factory_name": factory_name, "resource_group": resource_group,
                              "subscription_id": subscription_id})
    except Exception as exc:
        logger.error("Error listing triggers for %s: %s", factory_name, exc)
    return triggers

def get_adf_costs(subscription_id: str, days: int = 30, resource_groups: List[str] = None, start_date=None, end_date=None) -> List[Dict]:
    # Query Azure Cost Management REST API for resource-level costs and
    # return simplified records for ADF factories.
    import requests
    cred = _get_credential()
    token = cred.get_token("https://management.azure.com/.default").token
    now = datetime.now(timezone.utc)
    start = start_date or (now - timedelta(days=days))
    end = end_date or now
    url = (f"https://management.azure.com/subscriptions/{subscription_id}/"
           f"providers/Microsoft.CostManagement/query?api-version=2023-11-01")
    resource_filter = {"dimensions": {"name": "ResourceType", "operator": "In",
                                           "values": ["microsoft.datafactory/factories"]}}
    if resource_groups:
        resource_filter = {
            "and": [
                resource_filter,
                {"dimensions": {"name": "ResourceGroupName", "operator": "In", "values": resource_groups}}
            ]
        }
    payload = {
        "type": "ActualCost",
        "dataSet": {
            "granularity": "None",
            "aggregation": {"totalCostUSD": {"name": "CostUSD", "function": "Sum"}},
            "grouping": [{"type": "Dimension", "name": "ResourceId"},
                         {"type": "Dimension", "name": "ResourceGroupName"},
                         {"type": "Dimension", "name": "MeterCategory"}],
            "filter": resource_filter,
        },
        "timeframe": "Custom",
        "timePeriod": {"from": start.strftime("%Y-%m-%dT00:00:00Z"),
                       "to": end.strftime("%Y-%m-%dT23:59:59Z")},
    }
    results = []
    try:
        resp = requests.post(url, json=payload,
                             headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        columns = [c["name"] for c in data.get("properties", {}).get("columns", [])]
        for row in data.get("properties", {}).get("rows", []):
            rec = dict(zip(columns, row))
            rid = rec.get("ResourceId", "")
            results.append({"factory_name": rid.split("/")[-1] if rid else "unknown",
                             "resource_id": rid, "resource_group": rec.get("ResourceGroupName", ""),
                             "cost_usd": float(rec.get("CostUSD", rec.get("Cost", 0))),
                             "meter_category": rec.get("MeterCategory", "")})
    except Exception as exc:
        logger.error("Error fetching ADF costs for %s: %s", subscription_id, exc)
    return results


def _normalize_datetime(value):
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).astimezone(timezone.utc)
        except ValueError:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    return None


def get_adf_cost_history(subscription_id: str, days: int = 30, resource_groups: List[str] = None, start_date=None, end_date=None) -> List[Dict]:
    # Query Azure Cost Management for monthly ADF costs within the selected range.
    import requests
    cred = _get_credential()
    token = cred.get_token("https://management.azure.com/.default").token
    now = datetime.now(timezone.utc)
    start = _normalize_datetime(start_date) or (now - timedelta(days=days))
    end = _normalize_datetime(end_date) or now
    url = (f"https://management.azure.com/subscriptions/{subscription_id}/"
           f"providers/Microsoft.CostManagement/query?api-version=2023-11-01")
    resource_filter = {"dimensions": {"name": "ResourceType", "operator": "In",
                                           "values": ["microsoft.datafactory/factories"]}}
    if resource_groups:
        resource_filter = {
            "and": [
                resource_filter,
                {"dimensions": {"name": "ResourceGroupName", "operator": "In", "values": resource_groups}}
            ]
        }
    payload = {
        "type": "ActualCost",
        "timeframe": "Custom",
        "timePeriod": {
            "from": start.strftime("%Y-%m-%dT00:00:00Z"),
            "to": end.strftime("%Y-%m-%dT23:59:59Z"),
        },
        "dataSet": {
            "granularity": "Monthly",
            "aggregation": {"totalCostUSD": {"name": "CostUSD", "function": "Sum"}},
            "filter": resource_filter,
        },
    }
    results = []
    try:
        resp = requests.post(url, json=payload,
                             headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        columns = [c["name"] for c in data.get("properties", {}).get("columns", [])]
        for row in data.get("properties", {}).get("rows", []):
            rec = dict(zip(columns, row))
            period = rec.get("TimePeriod", rec.get("Date", rec.get("UsageDate", "")))
            if isinstance(period, str) and "T" in period:
                period = period.split("T")[0]
            results.append({
                "period": period,
                "cost_usd": float(rec.get("CostUSD", rec.get("totalCostUSD", 0) or 0)),
            })
    except Exception as exc:
        logger.error("Error fetching ADF cost history for %s: %s", subscription_id, exc)
    return results


def _extract_rg(resource_id: str) -> str:
    # Extract the resource group name from a typical ARM resource id
    parts = (resource_id or "").lower().split("/")
    try:
        idx = parts.index("resourcegroups")
        return resource_id.split("/")[idx + 1]
    except (ValueError, IndexError):
        return ""
