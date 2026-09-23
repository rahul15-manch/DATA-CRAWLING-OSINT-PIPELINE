/**
 * Flowiz Intelligence Platform — Search & Retrieval Intelligence View (M5)
 * Redesigned with Light Pastel Futuristic Theme (flowiz.biz)
 */

class SearchIntelView {
  constructor() {
    this.container = null;
  }

  render(container) {
    this.container = container;
    const leads = window.state.allLeads;
    const domains = new Set(leads.map(l => l.domain).filter(Boolean));
    const domainDiversity = leads.length > 0 ? Math.round((domains.size / leads.length) * 100) : 0;

    this.container.innerHTML = `
      <div class="view-header">
        <div>
          <div style="display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: var(--radius-pill); background: var(--flowiz-purple-badge-bg); border: 1px solid var(--flowiz-purple-badge-border); color: var(--flowiz-primary-purple-dark); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px;">
            <i class="fa-solid fa-brain"></i> Pillar 1 Retrieval Architecture
          </div>
          <h1 class="view-title">Search Intelligence & Query Engine</h1>
          <div class="view-subtitle">
            M5 Footprinting, multi-family query generation, operator compilation, and deterministic retrieval budgets.
          </div>
        </div>
      </div>

      <!-- Configured Query Budgets & Telemetry -->
      <div class="card" style="margin-bottom: 28px; border-radius: var(--radius-lg); box-shadow: var(--shadow-md);">
        <div class="card-header">
          <h3 class="card-title">
            <i class="fa-solid fa-gauge-high" style="color: var(--flowiz-primary-purple);"></i>
            M5 Configured Query Budgets & Engine Limits
          </h3>
          <span class="badge badge-success font-mono">DETERMINISTIC RATE-LIMITING</span>
        </div>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 16px;">
          <div style="padding: 16px 20px; background: var(--flowiz-bg-secondary); border-radius: var(--radius-md); border: 1px solid var(--flowiz-border);">
            <div class="text-caption text-muted" style="font-weight: 700;">MAX DIRECT QUERIES</div>
            <div class="font-mono text-accent" style="font-size: 26px; font-weight: 800; margin-top: 4px;">10</div>
            <div style="font-size: 11.5px; color: var(--flowiz-text-secondary); margin-top: 4px;">Primary entity root lookups</div>
          </div>

          <div style="padding: 16px 20px; background: var(--flowiz-bg-secondary); border-radius: var(--radius-md); border: 1px solid var(--flowiz-border);">
            <div class="text-caption text-muted" style="font-weight: 700;">MAX EXPANDED QUERIES</div>
            <div class="font-mono text-accent" style="font-size: 26px; font-weight: 800; margin-top: 4px;">20</div>
            <div style="font-size: 11.5px; color: var(--flowiz-text-secondary); margin-top: 4px;">Deep footprinting expansions</div>
          </div>

          <div style="padding: 16px 20px; background: var(--flowiz-bg-secondary); border-radius: var(--radius-md); border: 1px solid var(--flowiz-border);">
            <div class="text-caption text-muted" style="font-weight: 700;">MAX TOTAL SEARCH BUDGET</div>
            <div class="font-mono text-accent" style="font-size: 26px; font-weight: 800; margin-top: 4px;">25</div>
            <div style="font-size: 11.5px; color: var(--flowiz-text-secondary); margin-top: 4px;">Hard stop cap per pipeline run</div>
          </div>

          <div style="padding: 16px 20px; background: var(--flowiz-bg-secondary); border-radius: var(--radius-md); border: 1px solid var(--flowiz-border);">
            <div class="text-caption text-muted" style="font-weight: 700;">DOMAIN DIVERSITY YIELD</div>
            <div class="font-mono text-success" style="font-size: 26px; font-weight: 800; margin-top: 4px;">${domainDiversity}%</div>
            <div style="font-size: 11.5px; color: var(--flowiz-text-secondary); margin-top: 4px;">${domains.size} unique / ${leads.length} total (Measured)</div>
          </div>
        </div>
      </div>

      <!-- Query Families Grid -->
      <div class="card" style="margin-bottom: 28px;">
        <div class="card-header">
          <div>
            <h3 class="card-title">
              <i class="fa-solid fa-layer-group" style="color: var(--flowiz-primary-purple);"></i>
              The 7 Specialized Query Families
            </h3>
            <div class="card-subtitle">Algorithmic intent templates generated during Pillar 1 planning</div>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px;">
          ${this._renderFamilyCard(
            'Company / Market Discovery',
            'Broad discovery of organizations, product platforms, and corporate domains within a target vertical.',
            '"{keyword}" company OR "leading provider" OR "solutions"',
            'P1_ROOT'
          )}
          ${this._renderFamilyCard(
            'Contact Discovery',
            'Targeted extraction of customer support emails, sales desks, and official contact directories.',
            'site:{domain} inurl:contact OR inurl:about "email" OR "phone"',
            'P1_CONTACT'
          )}
          ${this._renderFamilyCard(
            'Leadership & Team',
            'Executive leadership identification, founders, VP Engineering, and board directors.',
            'site:{domain} (intitle:leadership OR intitle:management OR intitle:team)',
            'P1_LEADERSHIP'
          )}
          ${this._renderFamilyCard(
            'Careers & Hiring Intel',
            'Job openings, engineering team tech stacks, and geographic office expansion footprints.',
            'site:{domain} inurl:careers OR inurl:jobs "engineering" OR "manager"',
            'P1_CAREERS'
          )}
          ${this._renderFamilyCard(
            'Public Documents & Filings',
            'Whitepapers, security disclosures, annual reports, and technical specifications.',
            'site:{domain} filetype:pdf ("whitepaper" OR "overview" OR "annual report")',
            'P1_DOCS'
          )}
          ${this._renderFamilyCard(
            'Corporate Registry & Filings',
            'State entity registers, MCA India filings, SEC Edgar, and OpenCorporates data.',
            '"{company_name}" (site:zaubacorp.com OR site:opencorporates.com)',
            'P1_REGISTRY'
          )}
          ${this._renderFamilyCard(
            'Social & External Footprint',
            'Public social profiles across professional networks and developer communities.',
            '"{company_name}" (site:linkedin.com/company OR site:twitter.com)',
            'P1_SOCIAL'
          )}
        </div>
      </div>

      <!-- Operator Syntax Guide & Telemetry Status -->
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 24px;">
        <div class="card">
          <h3 class="card-title" style="margin-bottom: 16px;">
            <i class="fa-solid fa-code-compare" style="color: var(--flowiz-primary-purple);"></i>
            Supported Advanced Operators
          </h3>
          <div style="display: flex; flex-direction: column; gap: 10px;">
            ${this._renderOperatorRow('site:', 'Restricts results strictly to the designated target domain or TLD', 'site:example.com')}
            ${this._renderOperatorRow('inurl:', 'Requires specified substring within the returned URL path', 'inurl:contact')}
            ${this._renderOperatorRow('intitle:', 'Requires keywords inside the HTML title element', 'intitle:leadership')}
            ${this._renderOperatorRow('filetype:', 'Restricts results to indexed document extensions (pdf, docx, xls)', 'filetype:pdf')}
            ${this._renderOperatorRow('"phrase"', 'Enforces strict token exact matching in verbatim sequence', '"machine learning"')}
            ${this._renderOperatorRow('OR', 'Logical disjunction across multiple search expressions', 'termA OR termB')}
            ${this._renderOperatorRow('-exclusion', 'Negates domains or terms from appearing in the search yield', '-inurl:login')}
          </div>
        </div>

        <div class="card" style="padding: 0; overflow: hidden;">
          <div class="card-header" style="padding: 20px 24px; border-bottom: 1px solid var(--flowiz-border); margin-bottom: 0;">
            <h3 class="card-title">
              <i class="fa-solid fa-chart-pie" style="color: var(--flowiz-primary-purple);"></i>
              Pipeline Metric Observability Matrix
            </h3>
          </div>
          <div class="table-container">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Telemetry Metric</th>
                  <th>Value</th>
                  <th>Measurement Status</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td style="font-weight: 600;">Database Leads Extracted</td>
                  <td class="font-mono text-primary" style="font-weight: 700;">${leads.length}</td>
                  <td><span class="badge badge-success font-mono">Measured</span></td>
                </tr>
                <tr>
                  <td style="font-weight: 600;">Unique Domain Diversity</td>
                  <td class="font-mono text-accent" style="font-weight: 700;">${domains.size} unique (${domainDiversity}%)</td>
                  <td><span class="badge badge-success font-mono">Measured</span></td>
                </tr>
                <tr>
                  <td style="font-weight: 600;">Direct Query Budget</td>
                  <td class="font-mono text-primary">10 queries</td>
                  <td><span class="badge badge-neutral font-mono">Configured</span></td>
                </tr>
                <tr>
                  <td style="font-weight: 600;">Deep Footprinting Budget</td>
                  <td class="font-mono text-primary">20 queries</td>
                  <td><span class="badge badge-neutral font-mono">Configured</span></td>
                </tr>
                <tr>
                  <td style="font-weight: 600;">Live Search Latency</td>
                  <td class="font-mono text-muted">Variable per engine</td>
                  <td><span class="badge badge-neutral font-mono">Real-time</span></td>
                </tr>
                <tr>
                  <td style="font-weight: 600;">Historical Cache Hit Rate</td>
                  <td class="font-mono text-muted">N/A (in-memory)</td>
                  <td><span class="badge badge-neutral font-mono">Estimated</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;
  }

  _renderFamilyCard(name, desc, template, code) {
    return `
      <div style="padding: 16px 20px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
          <div style="font-weight: 700; font-size: 14.5px; color: var(--flowiz-text-primary);">${name}</div>
          <span class="badge badge-accent font-mono" style="font-size: 10px;">${code}</span>
        </div>
        <div class="text-secondary" style="font-size: 12.5px; line-height: 1.5; margin-bottom: 12px;">
          ${desc}
        </div>
        <div class="font-mono" style="font-size: 11.5px; padding: 8px 12px; background: var(--flowiz-bg-secondary); border-radius: var(--radius-sm); border: 1px solid var(--flowiz-border); color: var(--flowiz-primary-purple-dark); word-break: break-all; font-weight: 500;">
          ${template}
        </div>
      </div>
    `;
  }

  _renderOperatorRow(op, desc, example) {
    return `
      <div style="padding: 10px 14px; background: var(--flowiz-bg-secondary); border: 1px solid var(--flowiz-border); border-radius: var(--radius-sm); display: flex; justify-content: space-between; align-items: center; gap: 12px;">
        <div style="display: flex; align-items: center; gap: 10px;">
          <span class="badge badge-accent font-mono" style="font-size: 12px;">${op}</span>
          <span class="text-secondary" style="font-size: 12.5px; font-weight: 500;">${desc}</span>
        </div>
        <span class="font-mono text-muted" style="font-size: 11px;">${example}</span>
      </div>
    `;
  }
}

window.SearchIntelView = SearchIntelView;
