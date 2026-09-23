/**
 * Flowiz Intelligence Platform — Settings & Configuration View
 * Redesigned with Light Pastel Futuristic Theme (flowiz.biz)
 */

class SettingsView {
  constructor() {
    this.container = null;
    this.activeSection = 'general';
  }

  render(container) {
    this.container = container;

    this.container.innerHTML = `
      <div class="view-header">
        <div>
          <div style="display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: var(--radius-pill); background: var(--flowiz-purple-badge-bg); border: 1px solid var(--flowiz-purple-badge-border); color: var(--flowiz-primary-purple-dark); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px;">
            <i class="fa-solid fa-sliders"></i> Platform Configuration
          </div>
          <h1 class="view-title">Settings & Parameters</h1>
          <div class="view-subtitle">
            Inspect runtime configurations, rate limits, and safe network credentials.
          </div>
        </div>
      </div>

      <!-- Settings Layout (Left Nav + Right Settings Form) -->
      <div style="display: grid; grid-template-columns: 250px 1fr; gap: 24px;">
        <!-- Left Sub-navigation -->
        <div class="card" style="padding: 14px; border-radius: var(--radius-lg); height: fit-content;">
          <div style="display: flex; flex-direction: column; gap: 6px;">
            ${this._renderNavBtn('general', 'General Platform', 'fa-gear')}
            ${this._renderNavBtn('retrieval', 'Search & Footprinting', 'fa-magnifying-glass')}
            ${this._renderNavBtn('providers', 'OSINT Providers', 'fa-satellite')}
            ${this._renderNavBtn('network', 'Network & SSRF Shield', 'fa-shield-halved')}
            ${this._renderNavBtn('pipeline', 'Pipeline Parameters', 'fa-diagram-project')}
          </div>
        </div>

        <!-- Right Content Panel -->
        <div class="card" style="padding: 28px; border-radius: var(--radius-lg);">
          ${this._renderSectionContent()}
        </div>
      </div>
    `;

    this._bindEvents();
  }

  _renderNavBtn(id, label, icon) {
    const active = this.activeSection === id;
    return `
      <button class="settings-nav-btn ${active ? 'active' : ''}" data-section="${id}" style="display: flex; align-items: center; gap: 10px; width: 100%; padding: 11px 16px; text-align: left; background: ${active ? 'var(--flowiz-bg-secondary)' : 'transparent'}; border: 1px solid ${active ? 'var(--flowiz-border-accent)' : 'transparent'}; border-radius: var(--radius-pill); color: ${active ? 'var(--flowiz-primary-purple-dark)' : 'var(--flowiz-text-secondary)'}; font-size: 13.5px; font-weight: ${active ? '700' : '500'}; cursor: pointer; transition: all var(--transition-fast);">
        <i class="fa-solid ${icon}" style="width: 16px; color: ${active ? 'var(--flowiz-primary-purple)' : 'inherit'};"></i>
        <span>${label}</span>
      </button>
    `;
  }

  _renderSectionContent() {
    switch (this.activeSection) {
      case 'general':
        return `
          <h3 class="card-title" style="margin-bottom: 20px;">General Platform Configuration</h3>
          <div style="display: flex; flex-direction: column; gap: 18px;">
            <div>
              <label class="text-caption text-muted" style="display: block; margin-bottom: 6px; font-weight: 700;">PLATFORM IDENTIFIER</label>
              <input type="text" class="input font-mono" value="Flowiz Intelligence Platform v2.0 (Light AI Theme)" disabled style="background: var(--flowiz-bg-secondary);" />
            </div>
            <div>
              <label class="text-caption text-muted" style="display: block; margin-bottom: 6px; font-weight: 700;">CANONICAL STORAGE ENGINE</label>
              <input type="text" class="input font-mono" value="SQLite 3.x (flowiz_leads, WAL mode)" disabled style="background: var(--flowiz-bg-secondary);" />
            </div>
            <div>
              <label class="text-caption text-muted" style="display: block; margin-bottom: 6px; font-weight: 700;">REST API GATEWAY</label>
              <input type="text" class="input font-mono" value="FastAPI ASGI / Uvicorn" disabled style="background: var(--flowiz-bg-secondary);" />
            </div>
          </div>
        `;
      case 'retrieval':
        return `
          <h3 class="card-title" style="margin-bottom: 20px;">Search & Footprinting Parameters (M5)</h3>
          <div style="display: flex; flex-direction: column; gap: 18px;">
            <div>
              <label class="text-caption text-muted" style="display: block; margin-bottom: 6px; font-weight: 700;">SEARCH PROVIDER PRIORITY</label>
              <input type="text" class="input font-mono" value="playwright_google, google_html, duckduckgo, brave, bing, brightdata" disabled style="background: var(--flowiz-bg-secondary);" />
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
              <div>
                <label class="text-caption text-muted" style="display: block; margin-bottom: 6px; font-weight: 700;">MAX DIRECT QUERIES</label>
                <input type="text" class="input font-mono" value="10" disabled style="background: var(--flowiz-bg-secondary);" />
              </div>
              <div>
                <label class="text-caption text-muted" style="display: block; margin-bottom: 6px; font-weight: 700;">MAX TOTAL QUERIES BUDGET</label>
                <input type="text" class="input font-mono" value="25" disabled style="background: var(--flowiz-bg-secondary);" />
              </div>
            </div>
          </div>
        `;
      case 'providers':
        return `
          <h3 class="card-title" style="margin-bottom: 20px;">OSINT Provider Credentials & Masking</h3>
          <div class="card" style="margin-bottom: 20px; background: var(--flowiz-purple-badge-bg); border-left: 4px solid var(--flowiz-primary-purple); border-radius: var(--radius-md);">
            <div style="font-size: 13.5px; color: var(--flowiz-purple-badge-text); line-height: 1.5;">
              <i class="fa-solid fa-shield-halved text-accent" style="margin-right: 6px;"></i>
              <strong>Security Protocol Active:</strong> API keys and secrets are strictly masked and never transmitted in plaintext to client DOM.
            </div>
          </div>

          <div style="display: flex; flex-direction: column; gap: 14px;">
            <div style="padding: 14px 18px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs); display: flex; justify-content: space-between; align-items: center;">
              <div>
                <div style="font-weight: 700; font-size: 13.5px; color: var(--flowiz-text-primary);">SerpAPI Engine Key</div>
                <div class="font-mono text-muted" style="font-size: 12.5px;">••••••••••••••••••••••••••••••••</div>
              </div>
              <span class="badge badge-success font-mono"><i class="fa-solid fa-check"></i> Configured</span>
            </div>

            <div style="padding: 14px 18px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs); display: flex; justify-content: space-between; align-items: center;">
              <div>
                <div style="font-weight: 700; font-size: 13.5px; color: var(--flowiz-text-primary);">Hunter.io API Key</div>
                <div class="font-mono text-muted" style="font-size: 12.5px;">••••••••••••••••••••••••••••••••</div>
              </div>
              <span class="badge badge-warning font-mono">Deferred (HUNTER_ENABLED=false)</span>
            </div>

            <div style="padding: 14px 18px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs); display: flex; justify-content: space-between; align-items: center;">
              <div>
                <div style="font-weight: 700; font-size: 13.5px; color: var(--flowiz-text-primary);">Bright Data Proxy Key</div>
                <div class="font-mono text-muted" style="font-size: 12.5px;">••••••••••••••••••••••••••••••••</div>
              </div>
              <span class="badge badge-success font-mono"><i class="fa-solid fa-check"></i> Configured</span>
            </div>
          </div>
        `;
      case 'network':
        return `
          <h3 class="card-title" style="margin-bottom: 20px;">Network & SSRF Shield Hardening (M6)</h3>
          <div style="display: flex; flex-direction: column; gap: 14px;">
            <div style="padding: 14px 18px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs);">
              <div style="font-weight: 700; font-size: 14px; margin-bottom: 4px; color: var(--flowiz-text-primary);">Private IP / Loopback Filter</div>
              <div class="text-secondary" style="font-size: 12.5px;">Rejects requests targeting RFC 1918 ranges, 127.0.0.1, 169.254.169.254, and internal subnets.</div>
            </div>

            <div style="padding: 14px 18px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs);">
              <div style="font-weight: 700; font-size: 14px; margin-bottom: 4px; color: var(--flowiz-text-primary);">Per-Host Rate Limiter & Concurrency</div>
              <div class="text-secondary" style="font-size: 12.5px;">Enforces courteous scraping delays and prevents overwhelming remote web properties.</div>
            </div>

            <div style="padding: 14px 18px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs);">
              <div style="font-weight: 700; font-size: 14px; margin-bottom: 4px; color: var(--flowiz-text-primary);">DNS Rebinding & Re-Resolution Guard</div>
              <div class="text-secondary" style="font-size: 12.5px;">Resolves IP before connecting and pins connection target to prevent DNS rebinding attacks.</div>
            </div>
          </div>
        `;
      case 'pipeline':
        return `
          <h3 class="card-title" style="margin-bottom: 20px;">Pipeline Execution Parameters</h3>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
            <div>
              <label class="text-caption text-muted" style="display: block; margin-bottom: 6px; font-weight: 700;">DEFAULT TARGET LEADS PER RUN</label>
              <input type="text" class="input font-mono" value="10" disabled style="background: var(--flowiz-bg-secondary);" />
            </div>
            <div>
              <label class="text-caption text-muted" style="display: block; margin-bottom: 6px; font-weight: 700;">DEFAULT TIMEOUT PER STAGE</label>
              <input type="text" class="input font-mono" value="45 seconds" disabled style="background: var(--flowiz-bg-secondary);" />
            </div>
            <div>
              <label class="text-caption text-muted" style="display: block; margin-bottom: 6px; font-weight: 700;">LEAD SCORE ALGORITHM</label>
              <input type="text" class="input font-mono" value="12-Factor Canonical Heuristic" disabled style="background: var(--flowiz-bg-secondary);" />
            </div>
            <div>
              <label class="text-caption text-muted" style="display: block; margin-bottom: 6px; font-weight: 700;">DATASET PERSISTENCE</label>
              <input type="text" class="input font-mono" value="flowiz_leads (Idempotent Upsert)" disabled style="background: var(--flowiz-bg-secondary);" />
            </div>
          </div>
        `;
      default:
        return '';
    }
  }

  _bindEvents() {
    this.container.querySelectorAll('.settings-nav-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this.activeSection = btn.getAttribute('data-section');
        this.render(this.container);
      });
    });
  }
}

window.SettingsView = SettingsView;
