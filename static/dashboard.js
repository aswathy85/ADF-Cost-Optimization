/* ============================================================================
   Dashboard JavaScript for ADF Cost Optimizer
   ============================================================================ */

// Global state
let currentEnvironment = null;
let allEnvironments = {};
let analysisInProgress = false;
let allSubscriptions = [];
let allResourceGroups = {};

// ─────────────────────────────────────────────────────────────────────────────
// Initialization
// ─────────────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function() {
    console.log('Dashboard initialized');
    initializeUI();
    initializeDateRange();
    loadEnvironments();
    setupEventListeners();
    checkHealth();
    if (window.location.pathname === '/pipeline-insights') {
        initializePipelineInsights();
    }
});

function checkHealth() {
    fetch('/api/health')
        .then(r => r.json())
        .then(data => console.log('Health check OK:', data))
        .catch(err => console.error('Health check failed:', err));
}

// ─────────────────────────────────────────────────────────────────────────────
// Load Environments
// ─────────────────────────────────────────────────────────────────────────────

function loadEnvironments() {
    fetch('/api/environments')
        .then(r => r.json())
        .then(data => {
            if (!data.success) {
                showError('Failed to load environments: ' + data.error);
                return;
            }

            allEnvironments = data.config;
            const btnContainer = document.getElementById('environmentButtons');
            btnContainer.innerHTML = '';

            data.environments.forEach(env => {
                const cfg = data.config[env];
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'btn btn-outline-primary';
                btn.style.borderRadius = '0.375rem';
                btn.innerHTML = `
                    <span class="env-dot" style="background-color: #${cfg.color}"></span>
                    ${cfg.name}
                `;
                btn.addEventListener('click', (event) => selectEnvironment(env, event));
                btnContainer.appendChild(btn);
            });
            renderAnalysisEnvironmentChecks(data.environments);

            // Load mock data setting
            document.getElementById('mockDataToggle').checked = data.use_mock_data;
        })
        .catch(err => {
            console.error('Error loading environments:', err);
            showError('Failed to load environments. Check console for details.');
        });
}

function renderAnalysisEnvironmentChecks(environments) {
    const container = document.getElementById('analysisEnvironmentChecks');
    container.innerHTML = '';
    environments.forEach(env => {
        const cfg = allEnvironments[env];
        const row = document.createElement('div');
        row.className = 'form-check';
        row.innerHTML = `
            <input class="form-check-input analysis-env-check" type="checkbox" value="${env}" id="analysisEnv_${env}">
            <label class="form-check-label" for="analysisEnv_${env}">
                <span class="env-dot" style="background-color: #${cfg.color}"></span>
                ${cfg.name}
            </label>
        `;
        container.appendChild(row);
    });
}

function selectEnvironment(env, event) {
    currentEnvironment = env;
    
    // Update UI
    const buttons = document.querySelectorAll('#environmentButtons .btn');
    buttons.forEach(btn => btn.classList.remove('active'));
    event.target.closest('button').classList.add('active');
    const check = document.getElementById(`analysisEnv_${env}`);
    if (check) check.checked = true;

    // Show config panel
    document.getElementById('envConfigPanel').style.display = 'block';
    
    // Update environment name
    const envName = allEnvironments[env]?.name || env.toUpperCase();
    document.getElementById('envName').textContent = envName;

    // Load environment config
    loadEnvironmentConfig(env);
    
    // Clear previous results
    document.getElementById('resultsSection').style.display = 'none';
    document.getElementById('progressSection').style.display = 'none';
    document.getElementById('errorSection').style.display = 'none';
}

function loadEnvironmentConfig(env) {
    const cfg = allEnvironments[env];
    
    // Update subscriptions list
    updateSubscriptionsList(cfg.subscriptions || []);
    
    // Update resource groups list
    updateRgList(cfg.resource_groups || []);
    
    // Update storage account
    document.getElementById('storageAccount').value = cfg.storage_account || '';
}

function updateSubscriptionsList(subs) {
    const list = document.getElementById('subscriptionsList');
    
    if (!subs || subs.length === 0) {
        list.innerHTML = '<p class="text-muted mb-0">No subscriptions configured</p>';
        return;
    }

    let html = '';
    subs.forEach(sub => {
        html += `
            <div class="list-item">
                <span>${sub}</span>
                <i class="bi bi-x-circle" onclick="removeSubscription('${sub}')"></i>
            </div>
        `;
    });
    list.innerHTML = html;
}

function updateRgList(rgs) {
    const list = document.getElementById('rgList');
    
    if (!rgs || rgs.length === 0) {
        list.innerHTML = '<p class="text-muted mb-0">No resource groups configured</p>';
        return;
    }

    let html = '';
    rgs.forEach(rg => {
        html += `
            <div class="list-item">
                <span>${rg}</span>
                <i class="bi bi-x-circle" onclick="removeResourceGroup('${rg}')"></i>
            </div>
        `;
    });
    list.innerHTML = html;
}

function removeSubscription(sub) {
    allEnvironments[currentEnvironment].subscriptions = 
        allEnvironments[currentEnvironment].subscriptions.filter(s => s !== sub);
    updateSubscriptionsList(allEnvironments[currentEnvironment].subscriptions);
}

function removeResourceGroup(rg) {
    allEnvironments[currentEnvironment].resource_groups = 
        allEnvironments[currentEnvironment].resource_groups.filter(r => r !== rg);
    updateRgList(allEnvironments[currentEnvironment].resource_groups);
}

// ─────────────────────────────────────────────────────────────────────────────
// Event Listeners
// ─────────────────────────────────────────────────────────────────────────────

function setupEventListeners() {
    // Add Subscription
    document.getElementById('addSubBtn').addEventListener('click', showAddSubModal);
    
    // Add Resource Group
    document.getElementById('addRgBtn').addEventListener('click', showAddRgModal);
    
    // Save Configuration
    document.getElementById('saveConfigBtn').addEventListener('click', saveEnvironmentConfig);
    
    // Run Analysis
    document.getElementById('runAnalysisBtn').addEventListener('click', runAnalysis);
    
    // Download Report
    document.getElementById('downloadBtn').addEventListener('click', downloadReport);
    
    // View AI Pipeline Insights
    const insightsButton = document.getElementById('viewPipelineInsightsBtn');
    if (insightsButton) {
        insightsButton.addEventListener('click', () => {
            window.location.href = '/pipeline-insights';
        });
    }

    // Run Again
    document.getElementById('runAgainBtn').addEventListener('click', () => {
        document.getElementById('resultsSection').style.display = 'none';
        document.getElementById('statusContainer').innerHTML = `
            <p class="text-muted mb-0">
                <i class="bi bi-info-circle"></i> Ready to run analysis again
            </p>
        `;
    });
    
    // Close Error
    document.getElementById('closeErrorBtn').addEventListener('click', () => {
        document.getElementById('errorSection').style.display = 'none';
    });
}

// ─────────────────────────────────────────────────────────────────────────────
// Modals - Add Subscription
// ─────────────────────────────────────────────────────────────────────────────

function showAddSubModal() {
    const modal = new bootstrap.Modal(document.getElementById('addSubModal'));
    
    // Load subscriptions from Azure
    fetch(`/api/environments/${currentEnvironment}/subscriptions`)
        .then(r => r.json())
        .then(data => {
            if (!data.success) {
                alert('Error loading subscriptions: ' + data.error);
                return;
            }

            allSubscriptions = data.subscriptions;
            const select = document.getElementById('subSelect');
            select.innerHTML = '';

            if (!allSubscriptions || allSubscriptions.length === 0) {
                select.innerHTML = '<option value="">No subscriptions found for the signed-in Azure account.</option>';
                return;
            }

            allSubscriptions.forEach(sub => {
                const opt = document.createElement('option');
                opt.value = sub.id;
                opt.textContent = `${sub.name} (${sub.id})`;
                select.appendChild(opt);
            });
        })
        .catch(err => {
            console.error('Error loading subscriptions:', err);
            alert('Failed to load subscriptions. Please sign in to Azure or configure service principal environment variables.');
        });

    modal.show();
}

document.getElementById('confirmAddSubBtn').addEventListener('click', function() {
    const select = document.getElementById('subSelect');
    const selected = Array.from(select.selectedOptions).map(opt => opt.value).filter(Boolean);

    if (selected.length === 0) {
        alert('Please select at least one subscription');
        return;
    }

    // Add to current environment
    if (!allEnvironments[currentEnvironment].subscriptions) {
        allEnvironments[currentEnvironment].subscriptions = [];
    }
    selected.forEach(subId => {
        if (!allEnvironments[currentEnvironment].subscriptions.includes(subId)) {
            allEnvironments[currentEnvironment].subscriptions.push(subId);
        }
    });
    updateSubscriptionsList(allEnvironments[currentEnvironment].subscriptions);

    // Close modal
    bootstrap.Modal.getInstance(document.getElementById('addSubModal')).hide();
});

// ─────────────────────────────────────────────────────────────────────────────
// Modals - Add Resource Group
// ─────────────────────────────────────────────────────────────────────────────

function showAddRgModal() {
    const modal = new bootstrap.Modal(document.getElementById('addRgModal'));
    
    // Populate subscription select
    const rgSubSelect = document.getElementById('rgSubSelect');
    rgSubSelect.innerHTML = '<option value="">Select a subscription</option>';
    
    const subs = allEnvironments[currentEnvironment].subscriptions || [];
    subs.forEach(subId => {
        const sub = allSubscriptions.find(s => s.id === subId);
        const opt = document.createElement('option');
        opt.value = subId;
        opt.textContent = sub ? sub.name : subId;
        rgSubSelect.appendChild(opt);
    });

    // Load RGs when subscription selected
    rgSubSelect.addEventListener('change', function() {
        if (!this.value) return;

        fetch(`/api/environments/${currentEnvironment}/resource-groups`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ subscription_id: this.value })
        })
            .then(r => r.json())
            .then(data => {
                if (!data.success) {
                    alert('Error: ' + data.error);
                    return;
                }

                const rgSelect = document.getElementById('rgSelect');
                rgSelect.innerHTML = '';
                
                if (!data.resource_groups || data.resource_groups.length === 0) {
                    rgSelect.innerHTML = '<option value="">No resource groups found</option>';
                    return;
                }

                data.resource_groups.forEach(rg => {
                    const opt = document.createElement('option');
                    opt.value = rg;
                    opt.textContent = rg;
                    rgSelect.appendChild(opt);
                });
            })
            .catch(err => {
                console.error('Error loading resource groups:', err);
                alert('Failed to load resource groups');
            });
    });

    modal.show();
}

document.getElementById('confirmAddRgBtn').addEventListener('click', function() {
    const select = document.getElementById('rgSelect');
    const selected = Array.from(select.selectedOptions).map(opt => opt.value).filter(Boolean);

    if (selected.length === 0) {
        alert('Please select at least one resource group');
        return;
    }

    // Add to current environment
    if (!allEnvironments[currentEnvironment].resource_groups) {
        allEnvironments[currentEnvironment].resource_groups = [];
    }
    selected.forEach(rg => {
        if (!allEnvironments[currentEnvironment].resource_groups.includes(rg)) {
            allEnvironments[currentEnvironment].resource_groups.push(rg);
        }
    });
    updateRgList(allEnvironments[currentEnvironment].resource_groups);

    // Close modal
    bootstrap.Modal.getInstance(document.getElementById('addRgModal')).hide();
});

// ─────────────────────────────────────────────────────────────────────────────
// Save Configuration
// ─────────────────────────────────────────────────────────────────────────────

function saveEnvironmentConfig() {
    const subscriptions = allEnvironments[currentEnvironment].subscriptions || [];
    const resource_groups = allEnvironments[currentEnvironment].resource_groups || [];
    const storage_account = document.getElementById('storageAccount').value;

    if (subscriptions.length === 0 || resource_groups.length === 0) {
        alert('Please configure at least one subscription and one resource group');
        return;
    }

    fetch(`/api/environments/${currentEnvironment}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            subscriptions,
            resource_groups,
            storage_account
        })
    })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                showSuccess(`Configuration saved for ${currentEnvironment.toUpperCase()}`);
            } else {
                showError('Failed to save configuration: ' + data.error);
            }
        })
        .catch(err => {
            console.error('Error saving config:', err);
            showError('Error saving configuration');
        });
}

// ─────────────────────────────────────────────────────────────────────────────
// Run Analysis
// ─────────────────────────────────────────────────────────────────────────────

function runAnalysis() {
    const selectedEnvironments = getSelectedAnalysisEnvironments();
    if (selectedEnvironments.length === 0) {
        showError('Please select at least one environment in Analysis Scope');
        return;
    }

    const missingConfig = selectedEnvironments.filter(env => {
        const subscriptions = allEnvironments[env].subscriptions || [];
        const resource_groups = allEnvironments[env].resource_groups || [];
        return subscriptions.length === 0 || resource_groups.length === 0;
    });

    if (missingConfig.length > 0) {
        showError(`Please configure subscriptions and resource groups for: ${missingConfig.map(e => e.toUpperCase()).join(', ')}`);
        return;
    }

    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;
    if (!startDate || !endDate) {
        showError('Please select a start date and end date');
        return;
    }
    if (endDate < startDate) {
        showError('End date must be on or after start date');
        return;
    }

    if (analysisInProgress) {
        showError('Analysis is already in progress');
        return;
    }

    analysisInProgress = true;
    document.getElementById('runAnalysisBtn').disabled = true;

    const useMock = document.getElementById('mockDataToggle').checked;

    // Start analysis
    fetch('/api/run-analysis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            environments: selectedEnvironments,
            start_date: startDate,
            end_date: endDate,
            use_mock: useMock
        })
    })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                // Show progress section
                document.getElementById('progressSection').style.display = 'block';
                document.getElementById('resultsSection').style.display = 'none';
                document.getElementById('errorSection').style.display = 'none';
                
                // Poll for status
                pollAnalysisStatus();
            } else {
                showError('Failed to start analysis: ' + data.error);
                analysisInProgress = false;
                document.getElementById('runAnalysisBtn').disabled = false;
            }
        })
        .catch(err => {
            console.error('Error starting analysis:', err);
            showError('Error starting analysis');
            analysisInProgress = false;
            document.getElementById('runAnalysisBtn').disabled = false;
        });
}

function pollAnalysisStatus() {
    fetch('/api/status')
        .then(r => r.json())
        .then(data => {
            updateProgressUI(data);

            if (data.status === 'running') {
                setTimeout(pollAnalysisStatus, 1000);
            } else if (data.status === 'completed') {
                analysisInProgress = false;
                document.getElementById('runAnalysisBtn').disabled = false;
                showResults(data.result);
            } else if (data.status === 'error') {
                analysisInProgress = false;
                document.getElementById('runAnalysisBtn').disabled = false;
                showError(data.error || 'Unknown error occurred');
            }
        })
        .catch(err => console.error('Error polling status:', err));
}

function updateProgressUI(status) {
    document.getElementById('currentStep').textContent = status.current_step || '-';
    document.getElementById('progressText').textContent = status.progress + '%';
    document.getElementById('progressBar').style.width = status.progress + '%';
    document.getElementById('statusMessage').textContent = status.message || '-';
}

// ─────────────────────────────────────────────────────────────────────────────
// Results
// ─────────────────────────────────────────────────────────────────────────────

function showResults(result) {
    if (!result) return;

    document.getElementById('progressSection').style.display = 'none';
    document.getElementById('resultsSection').style.display = 'block';

    const tableBody = document.getElementById('resultsSummaryBody');
    tableBody.innerHTML = '';
    const envCosts = result.cost_by_environment || {};
    const envOrder = result.environments || Object.keys(envCosts);
    const forecastAvg = '$' + (result.forecast_monthly_average_usd ? result.forecast_monthly_average_usd.toFixed(2) : '0.00');
    const forecast6Month = '$' + (result.forecast_total_6_months_usd ? result.forecast_total_6_months_usd.toFixed(2) : '0.00');

    if (envOrder.length > 0) {
        envOrder.forEach(env => {
            const cost = envCosts[env] || 0;
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${env.toUpperCase()}</td>
                <td>${result.factories || '-'}</td>
                <td>${result.pipelines || '-'}</td>
                <td>$${cost.toFixed(2)}</td>
                <td>${forecastAvg}</td>
                <td>${forecast6Month}</td>
            `;
            tableBody.appendChild(row);
        });
    } else {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>All</td>
            <td>${result.factories || '-'}</td>
            <td>${result.pipelines || '-'}</td>
            <td>$${(result.total_cost ? result.total_cost.toFixed(2) : '0.00')}</td>
            <td>${forecastAvg}</td>
            <td>${forecast6Month}</td>
        `;
        tableBody.appendChild(row);
    }

    document.getElementById('statusContainer').innerHTML = `
        <p class="text-success">
            <i class="bi bi-check-circle"></i> Analysis completed successfully!
        </p>
    `;
}

function downloadReport() {
    window.location.href = '/api/download-report';
}

// ─────────────────────────────────────────────────────────────────────────────
// Pipeline Insights Page
// ─────────────────────────────────────────────────────────────────────────────

function initializePipelineInsights() {
    document.getElementById('insightsAlert').classList.add('d-none');
    document.getElementById('pipelineInsightsBody').innerHTML = `
        <tr><td colspan="10" class="text-center text-muted">Loading pipeline details...</td></tr>
    `;
    loadPipelineInsights();

    document.getElementById('refreshPipelineInsightsBtn').addEventListener('click', loadPipelineInsights);
    document.getElementById('insightsEnvironmentFilter').addEventListener('change', loadPipelineInsights);
    document.getElementById('insightsFactoryFilter').addEventListener('change', loadPipelineInsights);
}

function loadPipelineInsights() {
    const env = document.getElementById('insightsEnvironmentFilter').value;
    const factory = document.getElementById('insightsFactoryFilter').value;
    const query = new URLSearchParams();
    if (env) query.set('environment', env);
    if (factory) query.set('factory', factory);

    fetch(`/api/analysis/pipelines?${query.toString()}`)
        .then(r => r.json())
        .then(data => {
            if (!data.success) {
                document.getElementById('insightsAlert').classList.remove('d-none');
                document.getElementById('insightsAlert').textContent = data.error || 'Could not load pipelines.';
                document.getElementById('pipelineInsightsBody').innerHTML = '';
                return;
            }

            document.getElementById('insightsAlert').classList.add('d-none');
            populatePipelineFilters(data.environments, data.factories);
            renderPipelineInsightsTable(data.pipelines);
        })
        .catch(err => {
            console.error('Error loading pipeline insights:', err);
            document.getElementById('insightsAlert').classList.remove('d-none');
            document.getElementById('insightsAlert').textContent = 'Unable to load pipeline insights. Check analysis state.';
            document.getElementById('pipelineInsightsBody').innerHTML = '';
        });
}

function populatePipelineFilters(environments, factories) {
    const envSelect = document.getElementById('insightsEnvironmentFilter');
    const factorySelect = document.getElementById('insightsFactoryFilter');
    const selectedEnv = envSelect.value;
    const selectedFactory = factorySelect.value;

    envSelect.innerHTML = '<option value="">All Environments</option>';
    environments.forEach(env => {
        envSelect.innerHTML += `<option value="${env}" ${env === selectedEnv ? 'selected' : ''}>${env.toUpperCase()}</option>`;
    });

    factorySelect.innerHTML = '<option value="">All ADF</option>';
    factories.forEach(factory => {
        factorySelect.innerHTML += `<option value="${factory}" ${factory === selectedFactory ? 'selected' : ''}>${factory}</option>`;
    });
}

function renderPipelineInsightsTable(pipelines) {
    const body = document.getElementById('pipelineInsightsBody');
    body.innerHTML = '';

    if (!pipelines || pipelines.length === 0) {
        body.innerHTML = `
            <tr>
                <td colspan="10" class="text-center text-muted">No pipelines match the selected filters.</td>
            </tr>
        `;
        return;
    }

    pipelines.forEach(pipeline => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${pipeline.environment.toUpperCase()}</td>
            <td>${pipeline.factory_name}</td>
            <td>${pipeline.pipeline_name}</td>
            <td>${pipeline.run_count}</td>
            <td>$${pipeline.estimated_cost_usd.toFixed(2)}</td>
            <td>$${pipeline.actual_cost_usd.toFixed(2)}</td>
            <td>$${pipeline.avg_cost_per_run.toFixed(2)}</td>
            <td>${pipeline.cost_tier}</td>
            <td>${pipeline.last_run_status || '-'}</td>
            <td class="text-nowrap">
                <button class="btn btn-sm btn-outline-primary me-1" onclick="openPipelineSuggestions('${encodeURIComponent(pipeline.factory_name)}','${encodeURIComponent(pipeline.pipeline_name)}')">
                    <i class="bi bi-lightbulb"></i> Suggestions
                </button>
                <button class="btn btn-sm btn-outline-success" onclick="openPipelineGenerate('${encodeURIComponent(pipeline.factory_name)}','${encodeURIComponent(pipeline.pipeline_name)}')">
                    <i class="bi bi-code-slash"></i> Create Pipeline
                </button>
            </td>
        `;
        body.appendChild(row);
    });
}

function openPipelineSuggestions(factoryName, pipelineName) {
    const factory = decodeURIComponent(factoryName);
    const pipeline = decodeURIComponent(pipelineName);
    const content = document.getElementById('pipelineSuggestionsContent');
    content.innerHTML = '<p class="text-muted">Loading AI suggestions...</p>';
    const modal = new bootstrap.Modal(document.getElementById('pipelineSuggestionsModal'));
    modal.show();

    fetch(`/api/analysis/pipeline-suggestions?factory=${encodeURIComponent(factory)}&pipeline=${encodeURIComponent(pipeline)}`)
        .then(r => r.json())
        .then(data => {
            if (!data.success) {
                content.innerHTML = `<div class="alert alert-danger">${data.error || 'Unable to load suggestions.'}</div>`;
                return;
            }
            if (!data.suggestions || data.suggestions.length === 0) {
                content.innerHTML = '<p class="text-muted">No suggestions returned.</p>';
                return;
            }
            content.innerHTML = data.suggestions.map(s => `
                <div class="mb-3">
                    <h6>${s.issue_category} <span class="badge bg-secondary">${s.priority}</span></h6>
                    <p><strong>Why:</strong> ${s.issue_description}</p>
                    <p><strong>Suggestion:</strong> ${s.suggestion}</p>
                    <p><strong>Estimated Savings:</strong> ${s.estimated_saving_pct}% (~$${s.estimated_saving_usd.toFixed(2)})</p>
                    <pre class="bg-light p-3 rounded">${s.optimized_code_snippet}</pre>
                </div>
            `).join('');
        })
        .catch(err => {
            console.error('Error fetching pipeline suggestions:', err);
            content.innerHTML = '<div class="alert alert-danger">Unable to load suggestions. Check the browser console.</div>';
        });
}

function openPipelineGenerate(factoryName, pipelineName) {
    const factory = decodeURIComponent(factoryName);
    const pipeline = decodeURIComponent(pipelineName);
    const content = document.getElementById('pipelineGenerateContent');
    content.textContent = 'Generating optimized pipeline code...';
    const modal = new bootstrap.Modal(document.getElementById('pipelineGenerateModal'));
    modal.show();

    fetch(`/api/analysis/pipeline-generate?factory=${encodeURIComponent(factory)}&pipeline=${encodeURIComponent(pipeline)}`)
        .then(r => r.json())
        .then(data => {
            if (!data.success) {
                content.textContent = data.error || 'Unable to generate optimized code.';
                return;
            }
            content.textContent = data.generated_code || 'No code was generated.';
        })
        .catch(err => {
            console.error('Error generating pipeline code:', err);
            content.textContent = 'Unable to generate pipeline code. Check the browser console.';
        });
}

// ─────────────────────────────────────────────────────────────────────────────
// UI Helpers
// ─────────────────────────────────────────────────────────────────────────────

function showError(message) {
    document.getElementById('errorSection').style.display = 'block';
    document.getElementById('errorMessage').textContent = message;
}

function showSuccess(message) {
    const status = document.getElementById('statusContainer');
    status.innerHTML = `
        <div class="alert alert-success" role="alert">
            <i class="bi bi-check-circle"></i> ${message}
        </div>
    `;
}

function initializeUI() {
    // Initialize tooltips if needed
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

function initializeDateRange() {
    const today = new Date();
    const start = new Date();
    start.setDate(today.getDate() - 29);
    document.getElementById('endDate').value = today.toISOString().slice(0, 10);
    document.getElementById('startDate').value = start.toISOString().slice(0, 10);
}

function getSelectedAnalysisEnvironments() {
    return Array.from(document.querySelectorAll('.analysis-env-check:checked')).map(cb => cb.value);
}

// Hide sections by default
document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('envConfigPanel').style.display = 'none';
    document.getElementById('progressSection').style.display = 'none';
    document.getElementById('resultsSection').style.display = 'none';
    document.getElementById('errorSection').style.display = 'none';
    document.getElementById('adfListSection').style.display = 'none';
});
