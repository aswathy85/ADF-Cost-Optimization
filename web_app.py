"""web_app.py — Flask-based web application for ADF Cost Optimizer

Provides a web interface for:
- Selecting environments (dev, qa, uat, prod)
- Configuring subscriptions and resource groups per environment
- Running cost analysis and report generation
- Viewing generated reports and logs

Usage:
    python web_app.py              # runs on http://localhost:5000
    python web_app.py --port 8080  # custom port
"""
from __future__ import annotations
import argparse
import calendar
import copy
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread

from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from src.config import load_config, AppConfig
from src.cost_analyzer import build_report_payload
from src.mock_data import generate_mock_data
from src.report_generator import generate_excel_report
from src.genai_optimizer import run_ai_optimization, analyze_pipeline, run_ai_code_generation
from src.azure_client import list_subscriptions as azure_list_subscriptions
from src.azure_client import list_resource_groups as azure_list_resource_groups
from src.models import ReportPayload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# Global state for tracking analysis progress
analysis_state = {
    "status": "idle",  # idle, running, completed, error
    "current_step": "",
    "progress": 0,
    "message": "",
    "error": None,
    "result": None,
    "payload": None,
    "start_time": None,
    "selected_environment": None,
    "selected_environments": [],
}


def update_state(status=None, current_step=None, progress=None, message=None, error=None):
    """Update analysis state and log."""
    if status is not None:
        analysis_state["status"] = status
    if current_step is not None:
        analysis_state["current_step"] = current_step
    if progress is not None:
        analysis_state["progress"] = progress
    if message is not None:
        analysis_state["message"] = message
        if status and status != "error":
            envs = analysis_state.get("selected_environments") or []
            env = analysis_state.get("selected_environment")
            label = ", ".join(e.upper() for e in envs) if envs else (env.upper() if env else "")
            prefix = f"[{label}] " if label else ""
            logger.info(f"{prefix}{message}")
    if error is not None:
        analysis_state["error"] = error
        logger.error(f"Error: {error}")


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the main dashboard page."""
    return render_template("dashboard.html")


@app.route("/api/environments", methods=["GET"])
def get_environments():
    """Return available environments from config."""
    try:
        cfg = load_config("config.yaml")
        environments = list(cfg.analysis.environments.keys())
        
        # Load environment configurations
        env_config = {}
        for env in environments:
            env_config[env] = {
                "name": env.upper(),
                "patterns": cfg.analysis.environments[env].patterns,
                "color": cfg.analysis.environments[env].color,
            }
        
        # Load stored subscriptions/RGs per environment
        env_creds_path = Path("env_credentials.json")
        stored_creds = {}
        if env_creds_path.exists():
            with open(env_creds_path, "r") as f:
                stored_creds = json.load(f)
        
        for env in env_config:
            if env in stored_creds:
                env_config[env]["subscriptions"] = stored_creds[env].get("subscriptions", [])
                env_config[env]["resource_groups"] = stored_creds[env].get("resource_groups", [])
                env_config[env]["storage_account"] = stored_creds[env].get("storage_account", "")
            else:
                env_config[env]["subscriptions"] = []
                env_config[env]["resource_groups"] = []
                env_config[env]["storage_account"] = ""
        
        return jsonify({
            "success": True,
            "environments": environments,
            "config": env_config,
            "use_mock_data": cfg.use_mock_data
        })
    except Exception as exc:
        logger.error(f"Error loading environments: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/environments/<env>/subscriptions", methods=["GET"])
def list_subscriptions(env):
    """List available Azure subscriptions for the authenticated Azure identity."""
    try:
        subscriptions = azure_list_subscriptions()
        return jsonify({"success": True, "subscriptions": subscriptions})
    
    except Exception as exc:
        logger.error(f"Error listing subscriptions: {exc}")
        return jsonify({
            "success": False,
            "error": (
                "Could not list subscriptions. Sign in to Azure or configure "
                "AZURE_TENANT_ID, AZURE_CLIENT_ID, and AZURE_CLIENT_SECRET. "
                f"Details: {exc}"
            )
        }), 500


@app.route("/api/environments/<env>/resource-groups", methods=["POST"])
def list_resource_groups(env):
    """List resource groups for a subscription."""
    try:
        data = request.get_json()
        subscription_id = data.get("subscription_id")
        
        if not subscription_id:
            return jsonify({"success": False, "error": "subscription_id required"}), 400
        
        resource_groups = azure_list_resource_groups(subscription_id)
        return jsonify({"success": True, "resource_groups": resource_groups})
    
    except Exception as exc:
        logger.error(f"Error listing resource groups: {exc}")
        return jsonify({
            "success": False,
            "error": (
                "Could not list resource groups. Confirm your Azure sign-in has "
                f"access to this subscription. Details: {exc}"
            )
        }), 500


@app.route("/api/environments/<env>/config", methods=["POST"])
def save_environment_config(env):
    """Save subscription/RG configuration for an environment."""
    try:
        data = request.get_json()
        subscriptions = data.get("subscriptions", [])
        resource_groups = data.get("resource_groups", [])
        storage_account = data.get("storage_account", "")
        
        env_creds_path = Path("env_credentials.json")
        stored_creds = {}
        
        if env_creds_path.exists():
            with open(env_creds_path, "r") as f:
                stored_creds = json.load(f)
        
        stored_creds[env] = {
            "subscriptions": subscriptions,
            "resource_groups": resource_groups,
            "storage_account": storage_account,
            "updated_at": datetime.now().isoformat()
        }
        
        with open(env_creds_path, "w") as f:
            json.dump(stored_creds, f, indent=2)
        
        logger.info(f"Saved config for environment: {env}")
        return jsonify({"success": True, "message": f"Configuration saved for {env.upper()}"})
    
    except Exception as exc:
        logger.error(f"Error saving environment config: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/run-analysis", methods=["POST"])
def run_analysis():
    """Execute cost analysis for selected environments and generate report."""
    try:
        data = request.get_json()
        environments = data.get("environments") or []
        if not environments and data.get("environment"):
            environments = [data.get("environment")]
        environments = [env for env in environments if env]
        use_mock = data.get("use_mock", False)
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        
        if not environments:
            return jsonify({"success": False, "error": "at least one environment required"}), 400

        date_error = _validate_date_range(start_date, end_date)
        if date_error:
            return jsonify({"success": False, "error": date_error}), 400
        
        analysis_state["selected_environment"] = environments[0]
        analysis_state["selected_environments"] = environments
        analysis_state["status"] = "running"
        analysis_state["start_time"] = datetime.now()
        analysis_state["progress"] = 0
        analysis_state["current_step"] = ""
        analysis_state["message"] = ""
        analysis_state["error"] = None
        analysis_state["result"] = None

        # Run analysis in a background thread after state is initialized.
        thread = Thread(target=_run_analysis_worker, args=(environments, use_mock, start_date, end_date))
        thread.daemon = True
        thread.start()
        
        return jsonify({"success": True, "message": "Analysis started"})
    
    except Exception as exc:
        logger.error(f"Error starting analysis: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


def _validate_date_range(start_date: str | None, end_date: str | None) -> str | None:
    if not start_date or not end_date:
        return "start_date and end_date are required"
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        return "date range must use YYYY-MM-DD format"
    if end < start:
        return "end date must be on or after start date"
    return None


def _date_range_days(start_date: str, end_date: str) -> int:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    return max((end - start).days + 1, 1)


def _run_analysis_worker(environments: list[str], use_mock: bool, start_date: str, end_date: str):
    """Worker function to run analysis in background."""
    try:
        update_state(
            status="running",
            current_step="Loading configuration",
            progress=5,
            message="Loading configuration..."
        )
        
        base_cfg = load_config("config.yaml")
        base_cfg.analysis.date_range_days = _date_range_days(start_date, end_date)
        base_cfg.analysis.start_date = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        base_cfg.analysis.end_date = datetime.strptime(end_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )

        env_creds_path = Path("env_credentials.json")
        stored_creds = {}
        if env_creds_path.exists():
            with open(env_creds_path, "r") as f:
                stored_creds = json.load(f)
        
        # Collect data
        update_state(
            current_step="Collecting data",
            progress=15,
            message=f"Collecting ADF data for {', '.join(e.upper() for e in environments)}..."
        )

        if use_mock:
            payload = generate_mock_data(seed=base_cfg.mock_data_seed, days=base_cfg.analysis.date_range_days)
            payload.factories = [f for f in payload.factories if f.environment in environments]
            payload.triggers = [t for t in payload.triggers if t.environment in environments]
        else:
            payload = _build_multi_environment_payload(base_cfg, environments, stored_creds)

        payload.date_range_days = base_cfg.analysis.date_range_days
        payload.analysis_start_date = base_cfg.analysis.start_date
        payload.analysis_end_date = base_cfg.analysis.end_date
        payload.selected_environments = environments
        payload.selected_scope = _build_selected_scope(environments, stored_creds, base_cfg)
        _recalculate_payload_totals(payload)
        
        num_factories = len(payload.factories)
        num_pipelines = sum(len(f.pipelines) for f in payload.factories)
        
        update_state(
            current_step="Data collection complete",
            progress=40,
            message=f"Found {num_factories} ADF(s) with {num_pipelines} pipeline(s)"
        )
        
        # Generate GenAI suggestions
        update_state(
            current_step="Generating AI insights",
            progress=60,
            message="Analyzing with GenAI for optimization suggestions..."
        )
        
        try:
            payload.optimization_suggestions = run_ai_optimization(payload, base_cfg)
        except Exception as ai_exc:
            logger.warning(f"GenAI analysis skipped: {ai_exc}")
            payload.optimization_suggestions = []
        
        # Generate report
        update_state(
            current_step="Generating Excel report",
            progress=80,
            message="Creating Excel report with charts and analysis..."
        )
        
        output_path = generate_excel_report(payload, base_cfg)
        
        update_state(
            status="completed",
            current_step="Analysis complete",
            progress=100,
            message="Report generated successfully!"
        )
        
        analysis_state["result"] = {
            "factories": num_factories,
            "pipelines": num_pipelines,
            "total_cost": payload.total_cost_usd,
            "cost_by_environment": payload.cost_by_environment,
            "forecast_months": payload.forecast_months,
            "forecast_monthly_average_usd": payload.forecast_monthly_average_usd,
            "forecast_total_6_months_usd": payload.forecast_total_6_months_usd,
            "report_path": output_path,
            "generated_at": datetime.now().isoformat(),
            "environments": environments,
            "date_range": {"start": start_date, "end": end_date},
        }
        analysis_state["payload"] = payload
        
        logger.info(f"Analysis complete: {num_factories} factories, {num_pipelines} pipelines")
    
    except Exception as exc:
        logger.error(f"Error in analysis worker: {exc}", exc_info=True)
        update_state(
            status="error",
            error=str(exc),
            message=f"Error: {str(exc)}"
        )


def _build_multi_environment_payload(base_cfg: AppConfig, environments: list[str], stored_creds: dict) -> ReportPayload:
    combined = ReportPayload(
        generated_at=datetime.now(timezone.utc),
        date_range_days=base_cfg.analysis.date_range_days,
    )
    for idx, environment in enumerate(environments, 1):
        update_state(
            current_step="Collecting data",
            progress=min(15 + int(25 * idx / max(len(environments), 1)), 40),
            message=f"Scanning {environment.upper()}..."
        )
        cfg = copy.deepcopy(base_cfg)
        env_cfg = stored_creds.get(environment, {})
        cfg.azure.subscription_ids = env_cfg.get("subscriptions", cfg.azure.subscription_ids)
        cfg.azure.resource_groups = env_cfg.get("resource_groups", cfg.azure.resource_groups)
        env_payload = build_report_payload(cfg)
        for factory in env_payload.factories:
            if factory.subscription_id in cfg.azure.subscription_ids and factory.resource_group in cfg.azure.resource_groups:
                _force_environment(factory, environment)
                combined.factories.append(factory)
        for trigger in env_payload.triggers:
            if trigger.subscription_id in cfg.azure.subscription_ids and trigger.resource_group in cfg.azure.resource_groups:
                trigger.environment = environment
                combined.triggers.append(trigger)
    return combined


def _force_environment(factory, environment: str):
    factory.environment = environment
    for pipeline in factory.pipelines:
        pipeline.environment = environment
        for activity in pipeline.activities:
            activity.environment = environment


def _build_selected_scope(environments: list[str], stored_creds: dict, cfg: AppConfig) -> dict:
    scope = {}
    for env in environments:
        env_cfg = stored_creds.get(env, {})
        scope[env] = {
            "subscriptions": env_cfg.get("subscriptions", cfg.azure.subscription_ids),
            "resource_groups": env_cfg.get("resource_groups", cfg.azure.resource_groups),
        }
    return scope


def _recalculate_payload_totals(payload: ReportPayload):
    payload.total_cost_usd = round(sum(f.estimated_cost_usd for f in payload.factories), 4)
    env_costs = {}
    for f in payload.factories:
        env_costs[f.environment] = round(env_costs.get(f.environment, 0) + f.estimated_cost_usd, 4)
    payload.cost_by_environment = env_costs
    payload.cost_by_factory = {
        f.factory_name: round(f.estimated_cost_usd, 4)
        for f in payload.factories
    }
    if not getattr(payload, "forecast_months", None):
        payload.forecast_months, payload.forecast_monthly_average_usd, payload.forecast_total_6_months_usd = _build_payload_forecast(payload)


def _build_payload_forecast(payload: ReportPayload):
    end_dt = payload.analysis_end_date or payload.generated_at
    monthly_average = round(payload.total_cost_usd / max(payload.date_range_days, 1) * 30.4375, 2)
    forecast_months = [{
        "label": "Selected Range",
        "actual_cost_usd": round(payload.total_cost_usd, 2),
        "estimated_cost_usd": None,
    }]
    for i in range(1, 7):
        forecast_months.append({
            "label": _add_months(end_dt, i).strftime("%b %Y"),
            "actual_cost_usd": None,
            "estimated_cost_usd": monthly_average,
        })
    return forecast_months, monthly_average, round(monthly_average * 6, 2)


def _add_months(dt: datetime, months: int) -> datetime:
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


@app.route("/api/status", methods=["GET"])
def get_status():
    """Get current analysis status."""
    return jsonify({
        "status": analysis_state["status"],
        "current_step": analysis_state["current_step"],
        "progress": analysis_state["progress"],
        "message": analysis_state["message"],
        "error": analysis_state["error"],
        "result": analysis_state["result"],
        "elapsed_seconds": (
            (datetime.now() - analysis_state["start_time"]).total_seconds()
            if analysis_state["start_time"]
            else 0
        )
    })


@app.route("/api/download-report", methods=["GET"])
def download_report():
    """Download the generated report."""
    try:
        if not analysis_state.get("result") or not analysis_state["result"].get("report_path"):
            return jsonify({"error": "No report available"}), 404
        
        report_path = analysis_state["result"]["report_path"]
        if not os.path.exists(report_path):
            return jsonify({"error": "Report file not found"}), 404
        
        return send_file(report_path, as_attachment=True)
    
    except Exception as exc:
        logger.error(f"Error downloading report: {exc}")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/health", methods=["GET"])
def health_check():
    """Simple health endpoint for the dashboard."""
    return jsonify({"status": "ok", "analysis_status": analysis_state.get("status", "idle")})


def _find_pipeline(payload, factory_name: str, pipeline_name: str):
    for factory in getattr(payload, "factories", []):
        if factory.factory_name == factory_name:
            for pipeline in factory.pipelines:
                if pipeline.pipeline_name == pipeline_name:
                    return pipeline
    return None


def _serialize_pipeline_record(pipeline):
    return {
        "factory_name": pipeline.factory_name,
        "pipeline_name": pipeline.pipeline_name,
        "environment": pipeline.environment,
        "resource_group": pipeline.resource_group,
        "subscription_id": pipeline.subscription_id,
        "run_count": pipeline.run_count,
        "last_run_status": pipeline.last_run_status,
        "cost_tier": pipeline.cost_tier,
        "estimated_cost_usd": round(pipeline.estimated_cost_usd, 4),
        "actual_cost_usd": round(pipeline.actual_cost_usd, 4),
        "avg_cost_per_run": round(pipeline.avg_cost_per_run, 4),
        "avg_duration_sec": round(pipeline.avg_duration_sec, 2),
    }


@app.route("/api/analysis/pipelines", methods=["GET"])
def get_analysis_pipelines():
    payload = analysis_state.get("payload")
    if not payload:
        return jsonify({"success": False, "error": "No analysis payload available"}), 404

    env_filter = request.args.get("environment", "")
    factory_filter = request.args.get("factory", "")

    pipelines = []
    factories = set()
    environments = set()
    for factory in payload.factories:
        environments.add(factory.environment)
        if env_filter and factory.environment != env_filter:
            continue
        if factory_filter and factory.factory_name != factory_filter:
            continue
        factories.add(factory.factory_name)
        for pipeline in factory.pipelines:
            pipelines.append(_serialize_pipeline_record(pipeline))

    pipelines.sort(key=lambda x: x["estimated_cost_usd"], reverse=True)

    return jsonify({
        "success": True,
        "pipelines": pipelines,
        "factories": sorted(factories),
        "environments": sorted(environments)
    })


@app.route("/api/analysis/pipeline-suggestions", methods=["GET"])
def get_pipeline_suggestions():
    factory_name = request.args.get("factory")
    pipeline_name = request.args.get("pipeline")
    if not factory_name or not pipeline_name:
        return jsonify({"success": False, "error": "factory and pipeline query parameters are required"}), 400

    payload = analysis_state.get("payload")
    if not payload:
        return jsonify({"success": False, "error": "No analysis payload available"}), 404

    pipeline = _find_pipeline(payload, factory_name, pipeline_name)
    if not pipeline:
        return jsonify({"success": False, "error": "Pipeline not found"}), 404

    cfg = load_config("config.yaml")
    try:
        suggestions = analyze_pipeline(pipeline, cfg)
        return jsonify({"success": True, "suggestions": [s.__dict__ for s in suggestions]})
    except Exception as exc:
        logger.error(f"Error generating suggestions for {pipeline_name}: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/analysis/pipeline-generate", methods=["GET"])
def get_pipeline_generate():
    factory_name = request.args.get("factory")
    pipeline_name = request.args.get("pipeline")
    if not factory_name or not pipeline_name:
        return jsonify({"success": False, "error": "factory and pipeline query parameters are required"}), 400

    payload = analysis_state.get("payload")
    if not payload:
        return jsonify({"success": False, "error": "No analysis payload available"}), 404

    pipeline = _find_pipeline(payload, factory_name, pipeline_name)
    if not pipeline:
        return jsonify({"success": False, "error": "Pipeline not found"}), 404

    cfg = load_config("config.yaml")
    try:
        ai_response = run_ai_code_generation(pipeline, cfg)
        return jsonify({"success": True, "generated_code": ai_response})
    except Exception as exc:
        logger.error(f"Error generating optimized code for {pipeline_name}: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/pipeline-insights")
def pipeline_insights():
    return render_template("pipeline_insights.html")


@app.route("/api/reset", methods=["POST"])
def reset_analysis():
    """Reset analysis state."""
    analysis_state["status"] = "idle"
    analysis_state["current_step"] = ""
    analysis_state["progress"] = 0
    analysis_state["message"] = ""
    analysis_state["error"] = None
    analysis_state["result"] = None
    analysis_state["payload"] = None
    analysis_state["start_time"] = None
    return jsonify({"success": True})


# ─────────────────────────────────────────────────────────────────────────────
# Health and Info
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})


@app.route("/api/info", methods=["GET"])
def info():
    """Get application info."""
    try:
        cfg = load_config("config.yaml")
        return jsonify({
            "app_name": "ADF Cost Optimizer",
            "version": "2.0.0",
            "environments": list(cfg.analysis.environments.keys()),
            "date_range_days": cfg.analysis.date_range_days,
            "use_mock_data": cfg.use_mock_data,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Error Handlers
# ─────────────────────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def server_error(e):
    logger.error(f"Server error: {e}")
    return jsonify({"error": "Internal server error"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ADF Cost Optimizer Web App")
    parser.add_argument("--port", type=int, default=5000, help="Port to run on")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--debug", action="store_true", help="Run in debug mode")
    args = parser.parse_args()
    
    logger.info(f"Starting ADF Cost Optimizer Web App on {args.host}:{args.port}")
    logger.info(f"Open your browser to http://{args.host}:{args.port}")
    
    app.run(host=args.host, port=args.port, debug=args.debug)
