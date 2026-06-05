# ADF Cost Optimizer - Web Dashboard

A modern web application for managing Azure Data Factory cost optimization across multiple environments.

## Features

✨ **Environment Management**
- Select and configure dev, qa, uat, and prod environments
- Per-environment subscription and resource group configuration
- Storage account management for report output

📊 **Analysis & Reporting**
- Run cost analysis with a single click
- Real-time progress monitoring
- Automatic Excel report generation with charts and insights
- GenAI-powered optimization suggestions

🔐 **Azure Integration**
- Direct Azure API access for real-time ADF discovery
- Support for mock data for testing
- Multi-subscription scanning
- Resource group filtering

## Quick Start

### Prerequisites

1. **Python 3.9+**
2. **Azure CLI** - For subscription/resource group access
   ```bash
   # Install Azure CLI
   # Windows: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows
   # macOS: brew install azure-cli
   # Linux: curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
   
   # Login to Azure
   az login
   ```

3. **Dependencies**
   ```bash
   # From the project root directory
   pip install -r requirements.txt
   ```

### Running the Web App

```bash
# Basic usage (runs on http://localhost:5000)
python web_app.py

# Custom port
python web_app.py --port 8080

# Debug mode (auto-reload on file changes)
python web_app.py --debug

# Specific host binding
python web_app.py --host 0.0.0.0 --port 5000
```

Then open your browser to: **http://localhost:5000**

## Usage Guide

### 1. Select an Environment
Click on **DEV**, **QA**, **UAT**, or **PROD** button in the left sidebar to select an environment.

### 2. Configure Environment
For each environment, you need to set up:

- **Subscriptions**: Click "Add Subscription" to select Azure subscriptions to scan
- **Resource Groups**: Click "Add Resource Group" to select specific resource groups
- **Storage Account**: (Optional) Specify a storage account name for report storage

**Example Configuration:**
```
Environment: DEV
- Subscriptions: dev-subscription-1, dev-subscription-2
- Resource Groups: rg-dev-adf, rg-dev-shared
- Storage Account: devstorageaccount
```

### 3. Save Configuration
Click "Save Configuration" to store your settings for the environment.

**Note**: Configurations are saved locally in `env_credentials.json`

### 4. Run Analysis
Click the green "Run Analysis" button to start the cost analysis. The dashboard will show:
- Current processing step
- Real-time progress bar
- Status messages

### 5. View Results
Once complete, you'll see:
- Number of ADF instances found
- Total pipelines analyzed
- Estimated total cost
- Download button for the full Excel report

### 6. Download Report
Click "Download Report" to get a comprehensive Excel workbook with:
- Executive Summary
- Environment Comparison
- ADF Breakdown
- Pipeline Analysis
- Cost Drivers
- AI-Generated Optimization Suggestions
- Optimized Code Snippets
- Power BI Data Model

## Configuration Files

### env_credentials.json
Stores per-environment subscription and resource group configurations:

```json
{
  "dev": {
    "subscriptions": ["sub-id-1", "sub-id-2"],
    "resource_groups": ["rg-dev-adf"],
    "storage_account": "devstg",
    "updated_at": "2024-01-15T10:30:00"
  },
  "prod": {
    "subscriptions": ["sub-id-prod"],
    "resource_groups": ["rg-prod-adf"],
    "storage_account": "prodstg",
    "updated_at": "2024-01-15T10:30:00"
  }
}
```

### config.yaml
Main application configuration (edit this file to set):
- Azure credentials
- Analysis parameters (date range, cost thresholds)
- GenAI settings
- Output paths

## API Endpoints

The web app provides these REST endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Main dashboard |
| `/api/health` | GET | Health check |
| `/api/environments` | GET | List available environments |
| `/api/environments/<env>/subscriptions` | GET | List Azure subscriptions |
| `/api/environments/<env>/resource-groups` | POST | List resource groups for subscription |
| `/api/environments/<env>/config` | POST | Save environment configuration |
| `/api/run-analysis` | POST | Start cost analysis |
| `/api/status` | GET | Get current analysis status |
| `/api/download-report` | GET | Download generated Excel report |
| `/api/reset` | POST | Reset analysis state |

## Troubleshooting

### "Could not list subscriptions. Make sure Azure CLI is installed and you're logged in."

**Solution:**
```bash
# Install Azure CLI (if not already installed)
# Windows: https://aka.ms/InstallAzureCLI
# macOS: brew install azure-cli
# Linux: curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Then login
az login

# Verify login
az account show
```

### "No subscriptions configured" or "No resource groups configured"

**Solution:**
- Make sure you're logged in with Azure CLI: `az login`
- Click "Add Subscription" to see available subscriptions
- Select the subscription, then click "Add Resource Group"

### Analysis fails with "Error connecting to Azure"

**Solution:**
- Verify your Azure CLI login: `az login`
- Check if you have the necessary permissions in the subscription
- Try checking the browser console (F12) for detailed error messages
- Use "Use Mock Data" toggle to test with sample data

### Report generation takes a long time

**Reasons:**
- Large number of ADF instances or pipelines
- Many days of historical data being analyzed
- GenAI processing of pipelines

**Solutions:**
- Reduce the date range in config.yaml
- Use the `--mock` option for testing
- Filter to specific resource groups

## Development

### Project Structure
```
ADF Cost Optimization/
├── web_app.py              # Main Flask application
├── config.yaml             # Configuration file
├── requirements.txt        # Python dependencies
├── templates/
│   └── dashboard.html      # Main web interface
├── static/
│   ├── dashboard.css       # Styling
│   └── dashboard.js        # Frontend logic
├── src/
│   ├── config.py           # Configuration loader
│   ├── azure_client.py     # Azure SDK wrappers
│   ├── cost_analyzer.py    # Cost analysis logic
│   ├── models.py           # Data models
│   ├── report_generator.py # Excel report generation
│   ├── genai_optimizer.py  # GenAI suggestions
│   └── mock_data.py        # Test data generator
└── reports/
    └── (generated reports go here)
```

### Adding New Environments

1. Edit `config.yaml`:
```yaml
analysis:
  environments:
    staging:  # New environment
      patterns: ["staging", "stg", "stage"]
      color: "9467BD"
```

2. The environment will appear in the web app automatically

### Extending the Analysis

To add custom analysis logic:
1. Modify `src/cost_analyzer.py`
2. Update `src/report_generator.py` to display new insights
3. Restart `web_app.py`

## Performance Tips

- **Filter by resource groups**: Only scan the RGs that contain ADF instances
- **Reduce date range**: Analyze fewer days to speed up data collection
- **Use mock data for testing**: Toggle "Use Mock Data" to test without Azure calls
- **Monitor system resources**: Close unnecessary applications during analysis

## Security Notes

⚠️ **Important:**
- `env_credentials.json` contains subscription IDs and resource group names - do NOT commit to version control
- Add to `.gitignore`: `env_credentials.json`
- Use appropriate RBAC roles for service principals
- Rotate credentials regularly
- Never commit `config.yaml` with real subscription IDs to public repos

## Support

For issues or feature requests:
1. Check the troubleshooting section above
2. Review browser console (F12) for error messages
3. Check terminal output for detailed logs
4. Enable debug mode: `python web_app.py --debug`

## License

Internal use only - Microsoft

---

**Version**: 2.0.0  
**Last Updated**: 2024-01-15
