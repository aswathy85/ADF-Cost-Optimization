# ADF Cost Optimizer 🏭

> Multi-environment Azure Data Factory cost analysis, trigger monitoring, and **Gen AI powered optimization** — all exported to Excel with Power BI integration.

---

## What It Does

| Feature | Details |
|---|---|
| **Cost Hierarchy** | Subscription → Environment → Factory → Pipeline → Activity |
| **Multi-environment** | Dev / QA / UAT / Prod detected from factory name patterns |
| **Trigger Monitoring** | Enabled/disabled triggers with unexpected-state alerts |
| **Gen AI Optimization** | Claude analyses each pipeline's JSON + run metrics → actionable suggestions |
| **Savings Estimates** | Per-pipeline USD saving estimate with priority and effort rating |
| **Optimized Code** | Ready-to-paste ADF JSON snippets for each recommendation |
| **Excel Report** | 11 formatted sheets with charts, colour coding, drill-down tables |
| **Power BI Model** | Star-schema fact table CSV ready for Power BI Desktop import |

---

## Report Sheets

| Sheet | Level | Contents |
|---|---|---|
| 📋 Cover | — | Table of contents |
| 📊 Executive Summary | High | KPIs, cost by env, top 10 pipelines, bar chart |
| 🌍 Environment Comparison | High | Dev/QA/UAT/Prod side-by-side with pie chart |
| 🏭 ADF Factory Breakdown | Mid | Cost per factory, trigger counts, cost tier |
| 🔗 Pipeline Cost Report | Mid | Cost per pipeline, runs, avg cost/run |
| ⚡ Activity Cost Report | Low | Cost per activity, DIU-hours, drilldown |
| 🔍 Cost Drivers Analysis | Mid | Cost by activity type, root-cause top 20 |
| 🔔 Trigger Status Report | Mid | All triggers with enabled/disabled status + alerts |
| 🤖 AI Optimization | High | Gen AI suggestions, saving %, saving USD, priority |
| 💡 Optimized Pipeline Code | — | Copy-paste ADF JSON for each recommendation |
| 📈 Power BI Data Model | — | Flat fact table for Power BI import |

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — add ANTHROPIC_API_KEY and Azure credentials
```

Edit `config.yaml`:
- Add your Azure `subscription_ids`
- Set `use_mock_data: false` for live Azure data
- Adjust `cost_thresholds` if needed

### 3. Run

```bash
# Demo with mock data (no Azure needed)
python main.py --mock

# Live Azure data with Gen AI optimization
python main.py

# Skip AI (faster, no API key needed)
python main.py --mock --no-ai

# Last 14 days only
python main.py --mock --days 14
```

Report is saved to `./reports/ADF_Cost_Optimization_Report.xlsx`

---

## Azure Authentication

The tool uses `DefaultAzureCredential` which supports:
- **Service Principal** → set `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID` in `.env`
- **Azure CLI** → run `az login` before executing
- **Managed Identity** → works automatically on Azure VMs/containers

Minimum required RBAC roles:
| Role | Scope | Purpose |
|---|---|---|
| `Reader` | Subscription | List factories, pipelines, triggers |
| `Cost Management Reader` | Subscription | Query actual costs |

---

## Gen AI Optimization

Set `ANTHROPIC_API_KEY` in `.env`. The optimizer:
1. Selects the top N most expensive pipelines (configurable in `config.yaml`)
2. Sends the full pipeline JSON definition + run metrics to Claude
3. Receives structured suggestions with: issue category, description, recommendation, saving %, optimized code snippet
4. Falls back to rule-based heuristics if no API key is set

### Detected Issue Categories
- High DIU Setting
- Full Load Instead of Delta
- Unoptimised Data Flow
- Excessive Activity Runs
- No Parallelism
- Redundant Activities
- Wrong IR Type
- Large Data Movement
- Missing Caching
- Inefficient Sink

---

## Power BI Setup

1. Open Power BI Desktop
2. **Get Data → Excel Workbook** → select `ADF_Cost_Optimization_Report.xlsx`
3. Import sheet `📈 Power BI Data Model` as the **Fact table**
4. Optionally import `PowerBI_DataModel.csv` for scheduled refresh
5. Build drill-down hierarchy: **Environment → FactoryName → PipelineName → ActivityName**
6. Recommended slicers: `CostTier`, `Environment`, `ActivityType`
7. Key measures to create in DAX:
   ```dax
   Total Cost = SUM(FactTable[CostUSD])
   Avg Cost Per Run = DIVIDE(SUM(FactTable[CostUSD]), SUM(FactTable[RunCount]))
   ```

---

## Project Structure

```
adf_cost_optimizer/
├── main.py                  ← Entry point
├── config.yaml              ← Configuration
├── requirements.txt
├── .env.example             ← Copy to .env
├── reports/                 ← Output directory
└── src/
    ├── config.py            ← Config loader
    ├── models.py            ← Dataclasses
    ├── azure_client.py      ← Azure SDK wrappers
    ├── cost_analyzer.py     ← Cost hierarchy builder
    ├── mock_data.py         ← Test data generator
    ├── genai_optimizer.py   ← Anthropic Claude integration
    └── report_generator.py  ← Excel + CSV report builder
```

---

## Configuration Reference (`config.yaml`)

| Key | Description |
|---|---|
| `azure.subscription_ids` | List of Azure subscription IDs to scan |
| `azure.resource_groups` | Optional filter (empty = all RGs) |
| `analysis.date_range_days` | History window (default 30) |
| `analysis.environments` | Name patterns for env detection |
| `analysis.top_pipelines_for_ai` | How many pipelines to submit to AI |
| `cost_thresholds.high/medium/low` | USD thresholds for tier classification |
| `genai.model` | Anthropic model (default: claude-sonnet-4-20250514) |
| `use_mock_data` | `true` = use generated data, no Azure needed |

