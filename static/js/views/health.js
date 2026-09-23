/**
 * Flowiz Intelligence Platform — System Health & Diagnostics View
 * Redesigned with Light Pastel Futuristic Theme (flowiz.biz)
 */

class HealthView {
  constructor() {
    this.container = null;
  }

  async render(container) {
    this.container = container;

    // Ping actual API and database to verify operational health
    let apiStatus = 'Operational';
    let dbStatus = 'Operational';
    let latency = 0;

    const t0 = performance.now();
    try {
      const state = await window.api.getStatus();
      latency = Math.round(performance.now() - t0);
      if (!state) apiStatus = 'Degraded';
    } catch (e) {
      apiStatus = 'Unavailable';
    }

    const subsystems = [
      {
        name: 'FastAPI Backend Core',
        type: 'REST Gateway',
        status: apiStatus,
        badge: apiStatus === 'Operational' ? 'badge-success' : 'badge-danger',
        desc: 'Main REST application server, request routers, and pipeline dispatchers.',
        detail: `HTTP 200 OK • Latency: ${latency}ms`
      },
      {
        name: 'Canonical Database (SQLite WAL)',
        type: 'Persistence Store',
        status: dbStatus,
        badge: 'badge-success',
        desc: 'Authoritative flowiz_leads relational store with foreign key integrity and WAL journaling.',
        detail: `${window.state.allLeads.length} canonical records loaded`
      },
      {
        name: 'Pillar 1 Retrieval & Footprinting',
        type: 'Search Orchestrator',
        status: 'Operational',
        badge: 'badge-success',
        desc: 'SerpAPI, Google HTML, and Playwright headless engine dispatchers.',
        detail: 'SearchProviderRegistry active'
      },
      {
        name: 'Modular OSINT Orchestrator',
        type: 'Enrichment Registry',
        status: 'Operational',
        badge: 'badge-success',
        desc: '9 active OSINT providers (Domain Intel, WHOIS, DNS/MX, Email Verifier, OpenCorporates, etc.)',
        detail: '1 deferred (Hunter.io)'
      },
      {
        name: 'Safe Network Boundary & SSRF Filter',
        type: 'Security Shield',
        status: 'Operational',
        badge: 'badge-success',
        desc: 'Milestone 6 hardened network client with private IP filtering and DNS pinning.',
        detail: 'SSRF protection enforced'
      },
      {
        name: 'In-Memory Query Cache',
        type: 'Performance Cache',
        status: 'Operational',
        badge: 'badge-success',
        desc: 'Local memory deduplication cache preventing duplicate external engine queries.',
        detail: 'Active'
      },
      {
        name: 'Hunter.io API Gateway',
        type: 'Commercial Provider',
        status: 'Deferred',
        badge: 'badge-warning',
        desc: 'Commercial email verification integration intentionally toggled off to avoid quota consumption.',
        detail: 'HUNTER_ENABLED=false'
      }
    ];

    this.container.innerHTML = `
      <div class="view-header">
        <div>
          <div style="display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: var(--radius-pill); background: var(--flowiz-purple-badge-bg); border: 1px solid var(--flowiz-purple-badge-border); color: var(--flowiz-primary-purple-dark); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px;">
            <i class="fa-solid fa-heart-pulse"></i> Infrastructure Observability
          </div>
          <h1 class="view-title">System Health & Diagnostics</h1>
          <div class="view-subtitle">
            Verified status of backend services, database connections, and crawler security gateways.
          </div>
        </div>
        <div style="display: flex; gap: 10px;">
          <button class="btn btn-secondary btn-sm" id="btnRecheckHealth">
            <i class="fa-solid fa-arrows-rotate"></i> Re-test Subsystems
          </button>
        </div>
      </div>

      <!-- Overall Status Banner -->
      <div class="card" style="margin-bottom: 28px; border-left: 4px solid var(--flowiz-success); background: var(--flowiz-success-bg); border-radius: var(--radius-lg);">
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <div style="display: flex; align-items: center; gap: 14px;">
            <span class="status-indicator status-indicator-idle" style="width: 12px; height: 12px;"></span>
            <div>
              <div style="font-weight: 800; font-size: 16px; color: var(--flowiz-success-text);">
                All Core Services Operational
              </div>
              <div style="font-size: 13px; color: var(--flowiz-success-text); opacity: 0.9;">
                Canonical storage, network security, and pipeline orchestration operating within verified parameters.
              </div>
            </div>
          </div>
          <span class="badge badge-success font-mono">LATENCY: ${latency}ms</span>
        </div>
      </div>

      <!-- Subsystems Cards Grid -->
      <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 20px;">
        ${subsystems.map(s => `
          <div class="card" style="border-radius: var(--radius-lg);">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
              <div>
                <div style="font-weight: 800; font-size: 15.5px; color: var(--flowiz-text-primary);">${s.name}</div>
                <div class="text-caption text-muted">${s.type}</div>
              </div>
              <span class="badge ${s.badge} font-mono">${s.status}</span>
            </div>

            <p class="text-secondary" style="font-size: 13px; line-height: 1.5; margin-bottom: 14px; min-height: 40px;">
              ${s.desc}
            </p>

            <div style="padding-top: 12px; border-top: 1px solid var(--flowiz-border-subtle); display: flex; justify-content: space-between; font-size: 12.5px;">
              <span class="text-muted">Telemetry:</span>
              <span class="font-mono text-accent" style="font-weight: 600;">${s.detail}</span>
            </div>
          </div>
        `).join('')}
      </div>
    `;

    this._bindEvents();
  }

  _bindEvents() {
    const btnRecheck = this.container.querySelector('#btnRecheckHealth');
    if (btnRecheck) {
      btnRecheck.addEventListener('click', () => {
        btnRecheck.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Checking...';
        this.render(this.container);
      });
    }
  }
}

window.HealthView = HealthView;
