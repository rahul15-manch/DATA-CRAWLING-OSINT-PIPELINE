/**
 * Flowiz Intelligence Platform — Pipeline Monitor View
 * Redesigned with Light Pastel Futuristic Theme (flowiz.biz)
 */

class PipelineView {
  constructor() {
    this.container = null;
  }

  render(container) {
    this.container = container;
    const pipe = window.state.pipelineState;

    this.container.innerHTML = `
      <div class="view-header">
        <div>
          <div style="display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: var(--radius-pill); background: var(--flowiz-purple-badge-bg); border: 1px solid var(--flowiz-purple-badge-border); color: var(--flowiz-primary-purple-dark); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px;">
            <i class="fa-solid fa-microchip"></i> Ingestion & Transformation Engine
          </div>
          <h1 class="view-title">Pipeline Monitor</h1>
          <div class="view-subtitle">
            Visual architecture and live execution states across the 7 canonical pipeline stages.
          </div>
        </div>
        <div style="display: flex; gap: 10px;">
          <span class="badge ${pipe.status === 'running' ? 'badge-accent' : pipe.status === 'completed' ? 'badge-success' : 'badge-neutral'} font-mono">
            STATUS: ${pipe.status.toUpperCase()}
          </span>
        </div>
      </div>

      <!-- Live Execution Telemetry Bar -->
      <div class="card" style="margin-bottom: 28px; border-radius: var(--radius-lg); background: var(--flowiz-bg-secondary); border-color: var(--flowiz-primary-purple);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <span class="status-indicator ${pipe.status === 'running' ? 'status-indicator-running' : 'status-indicator-idle'}"></span>
            <span style="font-weight: 700; font-size: 14.5px; color: var(--flowiz-text-primary);">
              Pipeline Engine: <span class="font-mono text-accent">${pipe.keyword ? `"${window.api.escapeHtml(pipe.keyword)}"` : 'Standby / Ready'}</span>
            </span>
          </div>
          <span class="badge badge-accent font-mono">${pipe.stage} (${pipe.progress_pct}%)</span>
        </div>

        <div class="progress-bar" style="height: 8px; margin-bottom: 14px;">
          <div class="progress-fill" style="width: ${pipe.progress_pct}%"></div>
        </div>

        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px;">
          <div style="padding: 12px 16px; background: #FFFFFF; border-radius: var(--radius-md); border: 1px solid var(--flowiz-border); box-shadow: var(--shadow-xs);">
            <div class="text-caption text-muted" style="font-weight: 700;">TARGET ENTITIES FOUND</div>
            <div class="font-mono text-accent" style="font-weight: 800; font-size: 20px; margin-top: 2px;">${pipe.companies_found}</div>
          </div>
          <div style="padding: 12px 16px; background: #FFFFFF; border-radius: var(--radius-md); border: 1px solid var(--flowiz-border); box-shadow: var(--shadow-xs);">
            <div class="text-caption text-muted" style="font-weight: 700;">VERIFIED LEADS STORED</div>
            <div class="font-mono text-success" style="font-weight: 800; font-size: 20px; margin-top: 2px;">${pipe.leads_generated}</div>
          </div>
          <div style="padding: 12px 16px; background: #FFFFFF; border-radius: var(--radius-md); border: 1px solid var(--flowiz-border); box-shadow: var(--shadow-xs);">
            <div class="text-caption text-muted" style="font-weight: 700;">ACTIVE STAGE CODE</div>
            <div class="font-mono text-primary" style="font-weight: 800; font-size: 17px; margin-top: 2px;">${pipe.stage_code || 'IDLE'}</div>
          </div>
          <div style="padding: 12px 16px; background: #FFFFFF; border-radius: var(--radius-md); border: 1px solid var(--flowiz-border); box-shadow: var(--shadow-xs);">
            <div class="text-caption text-muted" style="font-weight: 700;">TOTAL ELAPSED TIME</div>
            <div class="font-mono" style="font-weight: 800; font-size: 20px; margin-top: 2px;">${pipe.elapsed_sec}s</div>
          </div>
        </div>
      </div>

      <!-- 7-Stage Architectural Flow -->
      <div class="card" style="margin-bottom: 28px; border-radius: var(--radius-lg);">
        <div class="card-header">
          <h3 class="card-title">
            <i class="fa-solid fa-diagram-project" style="color: var(--flowiz-primary-purple);"></i>
            Canonical 7-Stage Pipeline Architecture
          </h3>
          <span class="badge badge-success font-mono">FLOWIZ PIPELINE CONTRACT V2</span>
        </div>

        <div style="display: flex; flex-direction: column; gap: 14px;">
          ${this._renderStageCard(1, 'Discovery', 'Pillar 1 Footprinting', 'Executes multi-engine search across 7 query families, collecting candidate URLs and company root domains.', pipe.stage_code === 'P1_SEARCH')}
          ${this._renderStageCard(2, 'Cleaning & Normalization', 'Pillar 2 Normalizer', 'Deduplicates domains, removes tracking query parameters, and strips CDN/parked domains.', pipe.stage_code === 'P2_CLEAN')}
          ${this._renderStageCard(3, 'Network Verification', 'Pillar 3 Verifier', 'Executes safe HTTP probes, DNS lookups, and SSL validity checks with SSRF protection.', pipe.stage_code === 'P3_VERIFY')}
          ${this._renderStageCard(4, 'Modular OSINT Enrichment', 'ProviderRegistry', 'Orchestrates 9 active OSINT providers: WHOIS, MX, email regex, social links, tech stack, and corporate registry.', pipe.stage_code === 'P4_ENRICH')}
          ${this._renderStageCard(5, 'Canonical Finalization', 'LeadRecord Contract', 'Transforms enriched entity into canonical LeadRecord, enforcing data schemas and provenance audit stamps.', pipe.stage_code === 'P5_FINALIZE')}
          ${this._renderStageCard(6, 'Pillar 4 ETL', 'Quality Scoring', 'Computes multi-factor algorithmic lead score (0-100) and assigns High / Medium / Low quality tier.', pipe.stage_code === 'P6_ETL')}
          ${this._renderStageCard(7, 'Database Storage', 'flowiz_leads Store', 'Authoritative persistence into SQLite flowiz_leads with idempotent upsert based on domain uniqueness.', pipe.stage_code === 'P7_STORE')}
        </div>
      </div>
    `;
  }

  _renderStageCard(num, title, sub, desc, isActive) {
    const isCompleted = window.state.pipelineState.status === 'completed';
    const statusLabel = isActive ? 'RUNNING' : isCompleted ? 'COMPLETED' : 'STANDBY';
    const badgeClass = isActive ? 'badge-accent' : isCompleted ? 'badge-success' : 'badge-neutral';

    return `
      <div style="display: flex; align-items: center; gap: 18px; padding: 16px 20px; background: ${isActive ? 'var(--flowiz-bg-secondary)' : '#FFFFFF'}; border: 1px solid ${isActive ? 'var(--flowiz-primary-purple)' : 'var(--flowiz-border)'}; border-radius: var(--radius-md); box-shadow: var(--shadow-xs); transition: all 0.2s;">
        <div style="width: 38px; height: 38px; border-radius: 50%; background: ${isActive ? 'var(--flowiz-gradient-primary)' : 'var(--flowiz-purple-badge-bg)'}; border: 1px solid ${isActive ? 'transparent' : 'var(--flowiz-purple-badge-border)'}; display: flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-weight: 800; font-size: 13.5px; color: ${isActive ? '#FFFFFF' : 'var(--flowiz-primary-purple-dark)'}; flex-shrink: 0; box-shadow: ${isActive ? '0 4px 12px rgba(168, 85, 247, 0.3)' : 'none'};">
          ${num}
        </div>

        <div style="flex: 1;">
          <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 2px;">
            <div style="font-weight: 700; font-size: 14.5px; color: var(--flowiz-text-primary);">${title}</div>
            <span class="text-caption font-mono text-muted">(${sub})</span>
          </div>
          <div class="text-secondary" style="font-size: 12.5px; line-height: 1.5;">${desc}</div>
        </div>

        <div>
          <span class="badge ${badgeClass} font-mono" style="font-size: 11px;">${statusLabel}</span>
        </div>
      </div>
    `;
  }
}

window.PipelineView = PipelineView;
