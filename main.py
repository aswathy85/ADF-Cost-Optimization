"""main.py — ADF Cost Optimizer Entry Point

Top-level CLI runner for the ADF Cost Optimization tool.
This script wires configuration, decides whether to use mock or live Azure
data, runs optional GenAI analysis, and writes the Excel + PowerBI outputs.

Usage examples:
    python main.py                 # uses config.yaml (live Azure mode)
    python main.py --mock          # mock data, no Azure needed
    python main.py --no-ai         # skip Gen AI analysis
    python main.py --days 14       # override date range
    python main.py --output out.xlsx
    python main.py --mock --no-ai  # quickest demo run
"""
from __future__ import annotations
import argparse, logging, sys, time

# Lightweight console helpers — use colorama when available for nicer output.
try:
    import colorama
    from colorama import Fore, Style
    colorama.init(autoreset=True)
    # Console helpers: human-friendly step/warn/err/ok/info indicators
    def step(m): print(f"{Fore.GREEN}▶  {m}{Style.RESET_ALL}")
    def warn(m): print(f"{Fore.YELLOW}⚠  {m}{Style.RESET_ALL}")
    def err(m):  print(f"{Fore.RED}✗  {m}{Style.RESET_ALL}")
    def ok(m):   print(f"{Fore.GREEN}✔  {m}{Style.RESET_ALL}")
    def info(m): print(f"{Fore.CYAN}{m}{Style.RESET_ALL}")
except ImportError:
    # Fallback to plain text output if colorama is not installed.
    def step(m): print(f"▶  {m}")
    def warn(m): print(f"⚠  {m}")
    def err(m):  print(f"✗  {m}")
    def ok(m):   print(f"✔  {m}")
    def info(m): print(m)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

def banner():
    """Prints a simple ASCII banner to identify the tool on startup."""
    info("=" * 65)
    info("  ADF Cost Optimizer  |  Multi-Environment  |  Gen AI Powered")
    info("=" * 65)
    print()

def main():
    # Start: print banner and parse CLI arguments
    banner()
    parser = argparse.ArgumentParser(description="ADF Cost Optimizer")
    parser.add_argument("--config",  default="config.yaml")
    parser.add_argument("--mock",    action="store_true", help="Use mock data")
    parser.add_argument("--no-ai",   action="store_true", help="Skip Gen AI")
    parser.add_argument("--days",    type=int, default=None)
    parser.add_argument("--output",  default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if args.verbose: logging.getLogger().setLevel(logging.DEBUG)  # enable debug if requested

    # Load configuration file -> typed config object
    step("Loading configuration…")
    try:
        from src.config import load_config
        cfg = load_config(args.config)
    except FileNotFoundError as exc:
        err(f"Config not found: {exc}"); sys.exit(1)

    # Apply CLI overrides to loaded config
    if args.mock:   cfg.use_mock_data = True
    if args.days:   cfg.analysis.date_range_days = args.days
    if args.output: cfg.output.excel_path = args.output
    ok(f"Config loaded  [{'MOCK' if cfg.use_mock_data else 'LIVE'} mode | {cfg.analysis.date_range_days} days]")

    # Data collection: either generate mock payload or build from Azure APIs
    t0 = time.time()
    if cfg.use_mock_data:
        step("Generating mock ADF data…")
        from src.mock_data import generate_mock_data
        payload = generate_mock_data(seed=cfg.mock_data_seed, days=cfg.analysis.date_range_days)
    else:
        step("Connecting to Azure…")
        # If subscriptions are not replaced in config, fall back to mock with warnings
        if not cfg.azure.subscription_ids or "your-subscription" in cfg.azure.subscription_ids[0]:
            warn("No real Azure subscription IDs found — falling back to mock data.")
            warn("Edit config.yaml: set use_mock_data: false and add real subscription_ids.")
            from src.mock_data import generate_mock_data
            payload = generate_mock_data(seed=cfg.mock_data_seed, days=cfg.analysis.date_range_days)
        else:
            from src.cost_analyzer import build_report_payload
            payload = build_report_payload(cfg)

    # Quick summary of collected data counts and costs
    num_pls  = sum(len(f.pipelines) for f in payload.factories)
    num_acts = sum(len(p.activities) for f in payload.factories for p in f.pipelines)
    ok(f"Data ready  [{len(payload.factories)} factories | {num_pls} pipelines | {num_acts} activities | {len(payload.triggers)} triggers]  ({time.time()-t0:.1f}s)")
    info(f"   Total estimated cost: ${payload.total_cost_usd:,.2f} USD")
    for env in ["prod","uat","qa","dev"]:
        cost = payload.cost_by_environment.get(env, 0)
        if cost: print(f"   {env.upper():<6}  ${cost:,.2f}")

    # Optional GenAI analysis step (skippable via --no-ai)
    if not args.no_ai:
        step("Running Gen AI optimization analysis…")
        t1 = time.time()
        try:
            from src.genai_optimizer import run_ai_optimization
            payload.optimization_suggestions = run_ai_optimization(payload, cfg)
            total_savings = sum(s.estimated_saving_usd for s in payload.optimization_suggestions)
            ok(f"{len(payload.optimization_suggestions)} suggestions generated  [potential savings: ${total_savings:,.2f}]  ({time.time()-t1:.1f}s)")
        except Exception as exc:
            warn(f"AI analysis error: {exc}")
    else:
        warn("AI analysis skipped (--no-ai)")

    # Report generation: write Excel and export CSV for Power BI
    step("Generating Excel report…")
    t2 = time.time()
    try:
        from src.report_generator import generate_excel_report
        out_path = generate_excel_report(payload, cfg)
        ok(f"Report saved: {out_path}  ({time.time()-t2:.1f}s)")
    except Exception as exc:
        err(f"Report generation failed: {exc}")
        logger.exception("Report error")
        sys.exit(1)

    # Final completion summary and helpful follow-up instructions
    print()
    info("=" * 65)
    info(f"  COMPLETE  |  Total: {time.time()-t0:.1f}s")
    info("=" * 65)
    print(f"\n  📊 Excel Report  →  {out_path}")
    print(f"  📈 Power BI CSV  →  {cfg.output.powerbi_csv_path}")
    print("\n  Sheets:")
    for s in ["📋 Cover","📊 Executive Summary","🌍 Environment Comparison",
              "🏭 ADF Factory Breakdown","🔗 Pipeline Cost Report","⚡ Activity Cost Report",
              "🔍 Cost Drivers Analysis","🔔 Trigger Status Report",
              "🤖 AI Optimization","💡 Optimized Pipeline Code","📈 Power BI Data Model"]:
        ok(f"  {s}")
    print()
    print("  Power BI Setup:")
    print("    1. Open Power BI Desktop")
    print("    2. Get Data → Excel Workbook → select the report file")
    print("    3. Import '📈 Power BI Data Model' sheet as Fact table")
    print("    4. Build hierarchy: Environment → Factory → Pipeline → Activity")
    print("    5. Use Cost Tier, Priority slicers for drill-down\n")

if __name__ == "__main__":
    main()
