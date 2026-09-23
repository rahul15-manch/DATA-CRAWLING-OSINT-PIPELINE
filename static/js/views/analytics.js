/**
 * Flowiz Intelligence Platform — Analytics & Distribution View
 * Redesigned with Light Pastel Futuristic Theme (flowiz.biz)
 */

class AnalyticsView {
  constructor() {
    this.container = null;
  }

  render(container) {
    this.container = container;
    const leads = window.state.allLeads;

    if (!leads || leads.length === 0) {
      this.container.innerHTML = `
        <div class="view-header">
          <div>
            <h1 class="view-title">Intelligence Analytics</h1>
            <div class="view-subtitle">Aggregated metrics computed from flowiz_leads.</div>
          </div>
        </div>
        <div class="card empty-state" style="padding: 60px; border-radius: var(--radius-xl);">
          <div class="empty-state-icon"><i class="fa-solid fa-chart-line"></i></div>
          <div class="empty-state-title">No analytics available yet.</div>
          <div class="empty-state-description">Analytics will appear as Flowiz collects more intelligence.</div>
        </div>
      `;
      return;
    }

    // Quality breakdown
    let qHigh = 0, qMed = 0, qLow = 0;
    let hasEmail = 0, hasPhone = 0, hasSocial = 0, hasTech = 0;
    const industries = {};
    const scoreBuckets = { '0-20': 0, '21-40': 0, '41-60': 0, '61-80': 0, '81-100': 0 };

    leads.forEach(l => {
      // Quality
      const q = (l.lead_quality || 'Low').toLowerCase();
      if (q === 'high') qHigh++;
      else if (q === 'medium') qMed++;
      else qLow++;

      // Contacts
      if (Array.isArray(l.emails) && l.emails.length > 0) hasEmail++;
      if (Array.isArray(l.phones) && l.phones.length > 0) hasPhone++;
      if (l.social_links && Object.keys(l.social_links).length > 0) hasSocial++;
      if (Array.isArray(l.tech_stack) && l.tech_stack.length > 0) hasTech++;

      // Industry
      const ind = l.industry || l.company_type || 'Unclassified';
      industries[ind] = (industries[ind] || 0) + 1;

      // Score buckets
      const score = Number(l.lead_score) || 0;
      if (score <= 20) scoreBuckets['0-20']++;
      else if (score <= 40) scoreBuckets['21-40']++;
      else if (score <= 60) scoreBuckets['41-60']++;
      else if (score <= 80) scoreBuckets['61-80']++;
      else scoreBuckets['81-100']++;
    });

    const topIndustries = Object.entries(industries)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6);

    const total = leads.length;

    this.container.innerHTML = `
      <div class="view-header">
        <div>
          <div style="display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: var(--radius-pill); background: var(--flowiz-purple-badge-bg); border: 1px solid var(--flowiz-purple-badge-border); color: var(--flowiz-primary-purple-dark); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px;">
            <i class="fa-solid fa-chart-column"></i> Quantitative Intelligence
          </div>
          <h1 class="view-title">Pipeline Intelligence Analytics</h1>
          <div class="view-subtitle">
            Deterministic distributions calculated from ${total} authoritative records in canonical database.
          </div>
        </div>
        <div style="display: flex; gap: 10px;">
          <span class="badge badge-success font-mono"><i class="fa-solid fa-check"></i> REAL DATABASE METRICS</span>
        </div>
      </div>

      <!-- Top Row: Quality Distribution & Score Buckets -->
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 28px;">
        <!-- Lead Quality Distribution -->
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">
              <i class="fa-solid fa-filter-circle-dollar" style="color: var(--flowiz-primary-purple);"></i>
              Quality Distribution
            </h3>
            <span class="badge badge-accent font-mono">${total} LEADS</span>
          </div>

          <div style="display: flex; flex-direction: column; gap: 18px;">
            ${this._renderBarRow('High Quality', qHigh, total, 'var(--flowiz-success)')}
            ${this._renderBarRow('Medium Quality', qMed, total, 'var(--flowiz-warning)')}
            ${this._renderBarRow('Low Quality', qLow, total, 'var(--flowiz-text-muted)')}
          </div>
        </div>

        <!-- Score Buckets Distribution -->
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">
              <i class="fa-solid fa-chart-simple" style="color: var(--flowiz-primary-purple);"></i>
              Score Tier Breakdown (0–100)
            </h3>
          </div>

          <div style="display: flex; flex-direction: column; gap: 14px;">
            ${Object.entries(scoreBuckets).map(([bucket, count]) => 
              this._renderBarRow(`Score ${bucket}`, count, total, 'var(--flowiz-primary-purple)')
            ).join('')}
          </div>
        </div>
      </div>

      <!-- Bottom Row: Top Industries & Contact Completeness -->
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 24px;">
        <!-- Top Target Industries -->
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">
              <i class="fa-solid fa-industry" style="color: var(--flowiz-primary-purple);"></i>
              Top Target Industries
            </h3>
            <span class="badge badge-accent font-mono">TOP 6</span>
          </div>

          <div style="display: flex; flex-direction: column; gap: 14px;">
            ${topIndustries.map(([ind, count]) => 
              this._renderBarRow(ind, count, total, 'var(--flowiz-info)')
            ).join('')}
          </div>
        </div>

        <!-- Contact & Signal Completeness -->
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">
              <i class="fa-solid fa-bullseye" style="color: var(--flowiz-primary-purple);"></i>
              Enrichment Completeness
            </h3>
            <span class="badge badge-accent font-mono">SIGNAL PENETRATION</span>
          </div>

          <div style="display: flex; flex-direction: column; gap: 18px;">
            ${this._renderBarRow('Email Addresses Verified', hasEmail, total, 'var(--flowiz-success)')}
            ${this._renderBarRow('Direct Telephony / Phones', hasPhone, total, 'var(--flowiz-primary-purple)')}
            ${this._renderBarRow('Social Profiles Discovered', hasSocial, total, 'var(--flowiz-info)')}
            ${this._renderBarRow('Tech Stack Fingerprinted', hasTech, total, 'var(--flowiz-warning)')}
          </div>
        </div>
      </div>
    `;
  }

  _renderBarRow(label, count, total, color) {
    const pct = total > 0 ? Math.round((count / total) * 100) : 0;
    return `
      <div>
        <div style="display: flex; justify-content: space-between; font-size: 13.5px; margin-bottom: 6px;">
          <span style="font-weight: 600; color: var(--flowiz-text-primary);">${window.api.escapeHtml(label)}</span>
          <span class="font-mono text-muted">${count} (${pct}%)</span>
        </div>
        <div class="progress-bar">
          <div class="progress-fill" style="width: ${pct}%; background: ${color};"></div>
        </div>
      </div>
    `;
  }
}

window.AnalyticsView = AnalyticsView;
