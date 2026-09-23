/**
 * Flowiz Intelligence Platform — Overview Dashboard View
 * Redesigned with Light Pastel Futuristic Theme (flowiz.biz)
 */

class OverviewView {
  constructor() {
    this.container = null;
  }

  render(container) {
    this.container = container;
    const metrics = window.state.getMetrics();
    const leads = window.state.allLeads.slice(0, 8);
    const pipe = window.state.pipelineState;

    // Calculate quality breakdown
    let highQ = 0, medQ = 0, lowQ = 0;
    window.state.allLeads.forEach(l => {
      const q = (l.lead_quality || 'Low').toLowerCase();
      if (q === 'high') highQ++;
      else if (q === 'medium') medQ++;
      else lowQ++;
    });
    const total = window.state.allLeads.length || 1;
    const highPct = Math.round((highQ / total) * 100);
    const medPct = Math.round((medQ / total) * 100);
    const lowPct = Math.round((lowQ / total) * 100);

    this.container.innerHTML = `
      <!-- Hero Section -->
      <div style="margin-bottom: 32px; display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 20px;">
        <div style="max-width: 720px;">
          <div style="display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: var(--radius-pill); background: var(--flowiz-purple-badge-bg); border: 1px solid var(--flowiz-purple-badge-border); color: var(--flowiz-primary-purple-dark); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 12px;">
            <i class="fa-solid fa-wand-magic-sparkles"></i> AI Lead Intelligence Platform
          </div>
          <h1 style="font-size: 34px; font-weight: 800; line-height: 1.2; letter-spacing: -0.03em; margin: 0 0 10px 0; color: var(--flowiz-text-primary);">
            Discover High-Value Intelligence <span class="text-gradient">with AI</span>
          </h1>
          <div class="text-secondary" style="font-size: 15px; line-height: 1.6;">
            Autonomous crawling, multi-channel OSINT footprinting, and verified corporate intelligence unified into a single AI workspace.
          </div>
        </div>

        <div style="display: flex; gap: 12px;">
          <button class="btn btn-secondary" id="btnRefreshOverview">
            <i class="fa-solid fa-arrows-rotate"></i> Refresh Telemetry
          </button>
          <button class="btn btn-primary" id="btnQuickDiscover">
            <span>Start Discovery</span>
            <i class="fa-solid fa-arrow-right" style="font-size: 11px;"></i>
          </button>
        </div>
      </div>

      <!-- Live Pipeline Banner if Active -->
      ${pipe.status === 'running' ? `
        <div class="card" style="margin-bottom: 24px; border-color: var(--flowiz-primary-purple); background: var(--flowiz-bg-secondary);">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
            <div style="display: flex; align-items: center; gap: 10px;">
              <span class="status-indicator status-indicator-running"></span>
              <span style="font-weight: 700; color: var(--flowiz-text-primary);">
                Active Intelligence Pipeline: <span class="font-mono text-accent">"${window.api.escapeHtml(pipe.keyword)}"</span>
              </span>
            </div>
            <span class="badge badge-accent font-mono">${pipe.stage} (${pipe.progress_pct}%)</span>
          </div>
          <div class="progress-bar">
            <div class="progress-fill" style="width: ${pipe.progress_pct}%"></div>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 12.5px; color: var(--flowiz-text-secondary); margin-top: 10px;">
            <span>Found: <strong class="text-primary">${pipe.companies_found}</strong> targets</span>
            <span>Generated: <strong class="text-primary">${pipe.leads_generated}</strong> verified leads</span>
            <span>Elapsed: <strong class="text-primary font-mono">${pipe.elapsed_sec}s</strong></span>
          </div>
        </div>
      ` : ''}

      <!-- KPI Metrics Grid -->
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-title">
            <span>Total Discovered Leads</span>
            <div class="kpi-icon"><i class="fa-solid fa-database"></i></div>
          </div>
          <div class="kpi-value font-mono">${metrics.totalLeads}</div>
          <div class="kpi-trend">
            <i class="fa-solid fa-circle-check text-success"></i> Authoritative records in <span class="font-mono">flowiz_leads</span>
          </div>
        </div>

        <div class="kpi-card">
          <div class="kpi-title">
            <span>Verified Contacts</span>
            <div class="kpi-icon"><i class="fa-solid fa-envelope-circle-check"></i></div>
          </div>
          <div class="kpi-value font-mono">${metrics.verifiedLeads}</div>
          <div class="kpi-trend">
            <i class="fa-solid fa-check text-success"></i> Leads with valid email or phone
          </div>
        </div>

        <div class="kpi-card">
          <div class="kpi-title">
            <span>OSINT Enriched</span>
            <div class="kpi-icon"><i class="fa-solid fa-fingerprint"></i></div>
          </div>
          <div class="kpi-value font-mono">${metrics.enrichedLeads}</div>
          <div class="kpi-trend">
            <i class="fa-solid fa-diagram-project text-info"></i> DNS, SSL, Tech & Org Graph
          </div>
        </div>

        <div class="kpi-card">
          <div class="kpi-title">
            <span>Average Lead Score</span>
            <div class="kpi-icon"><i class="fa-solid fa-chart-line"></i></div>
          </div>
          <div class="kpi-value font-mono">${metrics.avgScore}<span style="font-size: 16px; color: var(--flowiz-text-muted);">/100</span></div>
          <div class="kpi-trend">
            <i class="fa-solid fa-award text-warning"></i> Multi-factor algorithmic ranking
          </div>
        </div>
      </div>

      <!-- Intelligence Overview Grid (Quality + Recent Activity) -->
      <div style="display: grid; grid-template-columns: 340px 1fr; gap: 24px; margin-bottom: 28px;">
        <!-- Left: Lead Quality Distribution -->
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">
              <i class="fa-solid fa-filter-circle-dollar" style="color: var(--flowiz-primary-purple);"></i>
              Quality Distribution
            </h3>
          </div>
          <div style="display: flex; flex-direction: column; gap: 18px;">
            <div>
              <div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 6px;">
                <span style="font-weight: 600; display: flex; align-items: center; gap: 6px;">
                  <span style="width: 8px; height: 8px; border-radius: 50%; background: var(--flowiz-success);"></span> High Quality
                </span>
                <span class="font-mono text-muted">${highQ} (${highPct}%)</span>
              </div>
              <div class="progress-bar">
                <div class="progress-fill" style="width: ${highPct}%; background: var(--flowiz-success);"></div>
              </div>
            </div>

            <div>
              <div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 6px;">
                <span style="font-weight: 600; display: flex; align-items: center; gap: 6px;">
                  <span style="width: 8px; height: 8px; border-radius: 50%; background: var(--flowiz-warning);"></span> Medium Quality
                </span>
                <span class="font-mono text-muted">${medQ} (${medPct}%)</span>
              </div>
              <div class="progress-bar">
                <div class="progress-fill" style="width: ${medPct}%; background: var(--flowiz-warning);"></div>
              </div>
            </div>

            <div>
              <div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 6px;">
                <span style="font-weight: 600; display: flex; align-items: center; gap: 6px;">
                  <span style="width: 8px; height: 8px; border-radius: 50%; background: var(--flowiz-text-muted);"></span> Low Quality
                </span>
                <span class="font-mono text-muted">${lowQ} (${lowPct}%)</span>
              </div>
              <div class="progress-bar">
                <div class="progress-fill" style="width: ${lowPct}%; background: var(--flowiz-text-muted);"></div>
              </div>
            </div>
          </div>

          <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--flowiz-border-subtle);">
            <div style="font-size: 12.5px; color: var(--flowiz-text-muted); line-height: 1.5;">
              Quality ranks are computed from 12 canonical signals: contact availability, verified MX records, SSL integrity, social proof, and decision-maker detection.
            </div>
          </div>
        </div>

        <!-- Right: Pipeline Execution Overview -->
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">
              <i class="fa-solid fa-network-wired" style="color: var(--flowiz-primary-purple);"></i>
              Pipeline Execution Engine
            </h3>
            <span class="badge badge-success font-mono">7 STAGES ACTIVE</span>
          </div>

          <div class="pipeline-grid" style="grid-template-columns: repeat(4, 1fr); margin-bottom: 14px;">
            <div class="pipeline-step ${pipe.stage_code === 'P1_SEARCH' ? 'active' : ''}">
              <div class="pipeline-step-num font-mono">STAGE 1</div>
              <div class="pipeline-step-title">Discovery</div>
              <div class="pipeline-step-sub">Pillar 1 Footprinting</div>
            </div>
            <div class="pipeline-step ${pipe.stage_code === 'P2_CLEAN' ? 'active' : ''}">
              <div class="pipeline-step-num font-mono">STAGE 2</div>
              <div class="pipeline-step-title">Cleaning</div>
              <div class="pipeline-step-sub">Dedupe & Normalization</div>
            </div>
            <div class="pipeline-step ${pipe.stage_code === 'P3_VERIFY' ? 'active' : ''}">
              <div class="pipeline-step-num font-mono">STAGE 3</div>
              <div class="pipeline-step-title">Verification</div>
              <div class="pipeline-step-sub">HTTP, DNS & SSL</div>
            </div>
            <div class="pipeline-step ${pipe.stage_code === 'P4_ENRICH' ? 'active' : ''}">
              <div class="pipeline-step-num font-mono">STAGE 4</div>
              <div class="pipeline-step-title">Enrichment</div>
              <div class="pipeline-step-sub">OSINT & Social Links</div>
            </div>
          </div>

          <div class="pipeline-grid" style="grid-template-columns: repeat(3, 1fr);">
            <div class="pipeline-step ${pipe.stage_code === 'P5_FINALIZE' ? 'active' : ''}">
              <div class="pipeline-step-num font-mono">STAGE 5</div>
              <div class="pipeline-step-title">Finalization</div>
              <div class="pipeline-step-sub">Canonical Validation</div>
            </div>
            <div class="pipeline-step ${pipe.stage_code === 'P6_ETL' ? 'active' : ''}">
              <div class="pipeline-step-num font-mono">STAGE 6</div>
              <div class="pipeline-step-title">Pillar 4 ETL</div>
              <div class="pipeline-step-sub">Transform & Scoring</div>
            </div>
            <div class="pipeline-step ${pipe.stage_code === 'P7_STORE' ? 'active' : ''}">
              <div class="pipeline-step-num font-mono">STAGE 7</div>
              <div class="pipeline-step-title">Database Storage</div>
              <div class="pipeline-step-sub">flowiz_leads Store</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Recent Discovered Intelligence Table -->
      <div class="card" style="padding: 0; overflow: hidden;">
        <div class="card-header" style="padding: 22px 24px; border-bottom: 1px solid var(--flowiz-border); margin-bottom: 0;">
          <div>
            <h3 class="card-title">
              <i class="fa-solid fa-bullseye" style="color: var(--flowiz-primary-purple);"></i>
              Recent Intelligence Targets
            </h3>
            <div class="card-subtitle">Verified entities retrieved from canonical database</div>
          </div>
          <button class="btn btn-secondary btn-sm" id="btnViewAllLeads">
            <span>View All ${metrics.totalLeads} Leads</span>
            <i class="fa-solid fa-arrow-right" style="font-size: 11px;"></i>
          </button>
        </div>

        <div class="table-container">
          <table class="data-table">
            <thead>
              <tr>
                <th>Target Entity</th>
                <th>Domain</th>
                <th>Industry</th>
                <th>Location</th>
                <th>Quality</th>
                <th>Lead Score</th>
                <th>Signals</th>
                <th style="text-align: right;">Action</th>
              </tr>
            </thead>
            <tbody>
              ${leads.map(lead => this._renderLeadRow(lead)).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;

    this._bindEvents();
  }

  _renderLeadRow(lead) {
    const q = (lead.lead_quality || 'Low').toLowerCase();
    const qBadge = q === 'high' ? 'badge-success' : q === 'medium' ? 'badge-warning' : 'badge-neutral';
    const hasEmail = Array.isArray(lead.emails) && lead.emails.length > 0;
    const hasPhone = Array.isArray(lead.phones) && lead.phones.length > 0;
    const hasTech = Array.isArray(lead.tech_stack) && lead.tech_stack.length > 0;
    const hasOrg = lead.org_graph && Object.keys(lead.org_graph).length > 0;

    return `
      <tr class="lead-row" data-domain="${window.api.escapeHtml(lead.domain || '')}" style="cursor: pointer;">
        <td style="font-weight: 700; color: var(--flowiz-text-primary);">
          ${window.api.escapeHtml(lead.company_name || 'Unknown Entity')}
        </td>
        <td>
          <span class="font-mono text-accent" style="font-size: 13px; font-weight: 600;">${window.api.escapeHtml(lead.domain || '—')}</span>
        </td>
        <td>
          <span class="text-secondary" style="font-size: 13px;">${window.api.escapeHtml(lead.industry || lead.company_type || 'Technology')}</span>
        </td>
        <td>
          <span class="text-muted" style="font-size: 13px;">${window.api.escapeHtml(lead.location || lead.country || '—')}</span>
        </td>
        <td>
          <span class="badge ${qBadge}">${window.api.escapeHtml(lead.lead_quality || 'Low')}</span>
        </td>
        <td>
          <div style="display: flex; align-items: center; gap: 8px;">
            <div class="lead-score-gauge">
              ${lead.lead_score || 0}
            </div>
            <div class="progress-bar" style="width: 50px; height: 5px;">
              <div class="progress-fill" style="width: ${Math.min(100, (lead.lead_score || 0))}%"></div>
            </div>
          </div>
        </td>
        <td>
          <div style="display: flex; gap: 8px; font-size: 13px;">
            ${hasEmail ? '<span title="Verified Email Available" class="text-success"><i class="fa-solid fa-envelope"></i></span>' : '<span class="text-muted" style="opacity: 0.3"><i class="fa-solid fa-envelope"></i></span>'}
            ${hasPhone ? '<span title="Phone Contact Available" class="text-accent"><i class="fa-solid fa-phone"></i></span>' : '<span class="text-muted" style="opacity: 0.3"><i class="fa-solid fa-phone"></i></span>'}
            ${hasTech ? '<span title="Tech Stack Fingerprinted" class="text-info"><i class="fa-solid fa-server"></i></span>' : ''}
            ${hasOrg ? '<span title="Org Graph Available" class="text-warning"><i class="fa-solid fa-sitemap"></i></span>' : ''}
          </div>
        </td>
        <td style="text-align: right;">
          <button class="btn btn-secondary btn-sm btn-inspect" data-domain="${window.api.escapeHtml(lead.domain || '')}">
            <i class="fa-solid fa-id-card"></i> Dossier ↗
          </button>
        </td>
      </tr>
    `;
  }

  _bindEvents() {
    const btnRefresh = this.container.querySelector('#btnRefreshOverview');
    if (btnRefresh) {
      btnRefresh.addEventListener('click', async () => {
        btnRefresh.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Refreshing...';
        try {
          const leads = await window.api.getAllLeads();
          window.state.setLeads(leads);
          this.render(this.container);
        } catch (e) {
          console.error(e);
          btnRefresh.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i> Refresh Telemetry';
        }
      });
    }

    const btnQuick = this.container.querySelector('#btnQuickDiscover');
    if (btnQuick) {
      btnQuick.addEventListener('click', () => {
        window.state.setView('discover');
      });
    }

    const btnViewAll = this.container.querySelector('#btnViewAllLeads');
    if (btnViewAll) {
      btnViewAll.addEventListener('click', () => {
        window.state.setView('leads');
      });
    }

    // Row clicks & Dossier buttons
    this.container.querySelectorAll('.btn-inspect').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const domain = btn.getAttribute('data-domain');
        const targetLead = window.state.allLeads.find(l => l.domain === domain);
        if (targetLead) {
          window.state.setSelectedLead(targetLead, 'overview');
        }
      });
    });

    this.container.querySelectorAll('.lead-row').forEach(row => {
      row.addEventListener('click', () => {
        const domain = row.getAttribute('data-domain');
        const targetLead = window.state.allLeads.find(l => l.domain === domain);
        if (targetLead) {
          window.state.setSelectedLead(targetLead, 'overview');
        }
      });
    });
  }
}

window.OverviewView = OverviewView;
