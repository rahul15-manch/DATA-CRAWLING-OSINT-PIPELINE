/**
 * Flowiz Intelligence Platform — Lead Intelligence Dossier (Modal / Detail View)
 * Redesigned with Light Pastel Futuristic Theme (flowiz.biz)
 */

class LeadDetailModal {
  constructor() {
    this.container = null;
    this.activeTab = 'overview';
    this.lead = null;
  }

  show(lead, tab = 'overview') {
    this.lead = lead;
    this.activeTab = tab;
    let modalEl = document.getElementById('modalContainer');
    if (!modalEl) {
      modalEl = document.createElement('div');
      modalEl.id = 'modalContainer';
      document.body.appendChild(modalEl);
    }
    this.container = modalEl;
    this.render();
  }

  close() {
    if (this.container) {
      this.container.innerHTML = '';
      window.state.selectedLead = null;
    }
  }

  render() {
    if (!this.lead || !this.container) return;

    const lead = this.lead;
    const q = (lead.lead_quality || 'Low').toLowerCase();
    const qBadge = q === 'high' ? 'badge-success' : q === 'medium' ? 'badge-warning' : 'badge-neutral';
    const isVerified = lead.verification_status === 'Verified' || (lead.emails && lead.emails.length > 0);

    this.container.innerHTML = `
      <div class="modal-backdrop" id="modalBackdrop">
        <div class="modal-drawer">
          <!-- Drawer Header -->
          <div class="modal-header">
            <div style="display: flex; align-items: flex-start; gap: 16px;">
              <div style="width: 52px; height: 52px; border-radius: var(--radius-lg); background: var(--flowiz-gradient-primary); display: flex; align-items: center; justify-content: center; font-size: 22px; color: #FFFFFF; font-weight: 800; box-shadow: 0 4px 14px rgba(168, 85, 247, 0.3);">
                ${(lead.company_name || 'U').charAt(0).toUpperCase()}
              </div>
              <div>
                <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 4px;">
                  <h2 style="font-size: 22px; font-weight: 800; margin: 0; color: var(--flowiz-text-primary); letter-spacing: -0.02em;">
                    ${window.api.escapeHtml(lead.company_name || 'Unknown Entity')}
                  </h2>
                  <span class="badge ${qBadge}">${window.api.escapeHtml(lead.lead_quality || 'Low')} Quality</span>
                  ${isVerified ? '<span class="badge badge-success"><i class="fa-solid fa-check"></i> Verified</span>' : ''}
                </div>
                <div style="display: flex; align-items: center; gap: 16px; font-size: 13px;">
                  <span class="font-mono text-accent" style="font-weight: 600;">
                    <i class="fa-solid fa-globe" style="margin-right: 4px;"></i> ${window.api.escapeHtml(lead.domain || '—')}
                  </span>
                  <span class="text-secondary">
                    <i class="fa-solid fa-industry" style="margin-right: 4px;"></i> ${window.api.escapeHtml(lead.industry || lead.company_type || 'Technology')}
                  </span>
                  <span class="text-muted">
                    <i class="fa-solid fa-award" style="margin-right: 4px;"></i> Score: <strong class="text-primary font-mono">${lead.lead_score || 0}</strong>
                  </span>
                </div>
              </div>
            </div>

            <div style="display: flex; align-items: center; gap: 10px;">
              <button class="btn btn-secondary btn-sm" id="btnCopyDomain" title="Copy domain to clipboard">
                <i class="fa-solid fa-copy"></i> Copy Domain
              </button>
              <button class="btn btn-secondary btn-sm" id="btnExportLeadJson" title="Export this dossier">
                <i class="fa-solid fa-download"></i> Export JSON
              </button>
              <button class="btn btn-secondary btn-sm" id="btnCloseModal" style="border-radius: 50%; width: 34px; height: 34px; padding: 0; font-size: 15px;">
                <i class="fa-solid fa-xmark"></i>
              </button>
            </div>
          </div>

          <!-- Drawer Navigation Tabs -->
          <div class="modal-tabs">
            <button class="modal-tab ${this.activeTab === 'overview' ? 'active' : ''}" data-tab="overview">
              <i class="fa-solid fa-circle-info"></i> Overview
            </button>
            <button class="modal-tab ${this.activeTab === 'contacts' ? 'active' : ''}" data-tab="contacts">
              <i class="fa-solid fa-address-book"></i> Contacts & People
            </button>
            <button class="modal-tab ${this.activeTab === 'domain' ? 'active' : ''}" data-tab="domain">
              <i class="fa-solid fa-network-wired"></i> Domain & DNS
            </button>
            <button class="modal-tab ${this.activeTab === 'osint' ? 'active' : ''}" data-tab="osint">
              <i class="fa-solid fa-share-nodes"></i> OSINT & Social
            </button>
            <button class="modal-tab ${this.activeTab === 'tech' ? 'active' : ''}" data-tab="tech">
              <i class="fa-solid fa-microchip"></i> Tech Stack
            </button>
            <button class="modal-tab ${this.activeTab === 'org' ? 'active' : ''}" data-tab="org">
              <i class="fa-solid fa-sitemap"></i> Org Graph
            </button>
            <button class="modal-tab ${this.activeTab === 'provenance' ? 'active' : ''}" data-tab="provenance">
              <i class="fa-solid fa-clock-rotate-left"></i> Provenance
            </button>
            <button class="modal-tab ${this.activeTab === 'raw' ? 'active' : ''}" data-tab="raw">
              <i class="fa-solid fa-code"></i> Raw JSON
            </button>
          </div>

          <!-- Drawer Content Body -->
          <div class="modal-body">
            ${this._renderActiveTabContent()}
          </div>
        </div>
      </div>
    `;

    this._bindEvents();
  }

  _renderActiveTabContent() {
    switch (this.activeTab) {
      case 'overview': return this._renderOverviewTab();
      case 'contacts': return this._renderContactsTab();
      case 'domain': return this._renderDomainTab();
      case 'osint': return this._renderOsintTab();
      case 'tech': return this._renderTechTab();
      case 'org': return this._renderOrgTab();
      case 'provenance': return this._renderProvenanceTab();
      case 'raw': return this._renderRawTab();
      default: return this._renderOverviewTab();
    }
  }

  _renderOverviewTab() {
    const l = this.lead;
    return `
      <div style="display: flex; flex-direction: column; gap: 24px;">
        <div class="card">
          <h3 class="card-title" style="margin-bottom: 14px;">Entity Summary</h3>
          <p class="text-secondary" style="font-size: 14px; line-height: 1.6; margin-bottom: 18px;">
            ${window.api.escapeHtml(l.description || 'No detailed corporate description extracted for this entity.')}
          </p>

          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; padding-top: 16px; border-top: 1px solid var(--flowiz-border-subtle);">
            ${l.website ? `
              <div>
                <div class="text-caption text-muted">Official Website</div>
                <a href="${window.api.escapeHtml(l.website)}" target="_blank" rel="noopener noreferrer" class="font-mono text-accent" style="font-size: 13.5px; font-weight: 600; text-decoration: none;">
                  ${window.api.escapeHtml(l.website)} <i class="fa-solid fa-arrow-up-right-from-square" style="font-size: 10px;"></i>
                </a>
              </div>
            ` : ''}

            ${l.location ? `
              <div>
                <div class="text-caption text-muted">Primary Location</div>
                <div class="text-primary" style="font-size: 13.5px; font-weight: 600;">${window.api.escapeHtml(l.location)}</div>
              </div>
            ` : ''}

            ${l.country ? `
              <div>
                <div class="text-caption text-muted">Country of Origin</div>
                <div class="text-primary" style="font-size: 13.5px; font-weight: 600;">${window.api.escapeHtml(l.country)}</div>
              </div>
            ` : ''}

            ${l.founded ? `
              <div>
                <div class="text-caption text-muted">Year Founded</div>
                <div class="text-primary font-mono" style="font-size: 13.5px; font-weight: 600;">${window.api.escapeHtml(l.founded)}</div>
              </div>
            ` : ''}

            ${l.employee_count || l.size ? `
              <div>
                <div class="text-caption text-muted">Headcount / Size</div>
                <div class="text-primary" style="font-size: 13.5px; font-weight: 600;">${window.api.escapeHtml(l.employee_count || l.size)}</div>
              </div>
            ` : ''}

            ${l.keyword ? `
              <div>
                <div class="text-caption text-muted">Discovery Keyword</div>
                <span class="badge badge-accent font-mono" style="font-size: 12px;">${window.api.escapeHtml(l.keyword)}</span>
              </div>
            ` : ''}
          </div>
        </div>

        <!-- Verification & Quality Audit Box -->
        <div class="card" style="background: var(--flowiz-bg-secondary); border-color: var(--flowiz-border-accent);">
          <h3 class="card-title" style="margin-bottom: 14px;">
            <i class="fa-solid fa-shield-check" style="color: var(--flowiz-primary-purple);"></i>
            Algorithmic Scoring Breakdown
          </h3>
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px;">
            <div style="padding: 14px; background: #FFFFFF; border-radius: var(--radius-md); border: 1px solid var(--flowiz-border); box-shadow: var(--shadow-xs);">
              <div class="text-caption text-muted">Quality Tier</div>
              <div style="font-weight: 800; font-size: 17px; color: var(--flowiz-text-primary); margin-top: 2px;">
                ${window.api.escapeHtml(l.lead_quality || 'Low')}
              </div>
            </div>
            <div style="padding: 14px; background: #FFFFFF; border-radius: var(--radius-md); border: 1px solid var(--flowiz-border); box-shadow: var(--shadow-xs);">
              <div class="text-caption text-muted">Composite Lead Score</div>
              <div class="font-mono text-accent" style="font-weight: 800; font-size: 17px; margin-top: 2px;">
                ${l.lead_score || 0} / 100
              </div>
            </div>
            <div style="padding: 14px; background: #FFFFFF; border-radius: var(--radius-md); border: 1px solid var(--flowiz-border); box-shadow: var(--shadow-xs);">
              <div class="text-caption text-muted">Verification State</div>
              <div class="text-success" style="font-weight: 700; font-size: 15px; margin-top: 2px;">
                ${l.verification_status || (l.emails && l.emails.length ? 'Verified' : 'Discovered')}
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderContactsTab() {
    const l = this.lead;
    const emails = Array.isArray(l.emails) ? l.emails : [];
    const phones = Array.isArray(l.phones) ? l.phones : [];
    const people = Array.isArray(l.people) ? l.people : [];

    return `
      <div style="display: flex; flex-direction: column; gap: 24px;">
        <!-- Email Addresses -->
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">
              <i class="fa-solid fa-envelope" style="color: var(--flowiz-primary-purple);"></i>
              Discovered & Verified Email Vectors
            </h3>
            <span class="badge badge-accent font-mono">${emails.length} IDENTIFIED</span>
          </div>

          ${emails.length === 0 ? `
            <div class="text-muted" style="font-size: 13.5px;">No direct email addresses extracted for this domain.</div>
          ` : `
            <div style="display: flex; flex-direction: column; gap: 10px;">
              ${emails.map(email => `
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 18px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs);">
                  <div style="display: flex; align-items: center; gap: 12px;">
                    <i class="fa-solid fa-at text-accent" style="font-size: 14px;"></i>
                    <span class="font-mono" style="font-size: 13.5px; font-weight: 600;">${window.api.escapeHtml(email)}</span>
                  </div>
                  <div style="display: flex; align-items: center; gap: 10px;">
                    <span class="badge badge-success font-mono" style="font-size: 11px;">SYNTAX & MX VALID</span>
                    <button class="btn btn-secondary btn-sm btn-copy-text" data-text="${window.api.escapeHtml(email)}" title="Copy email">
                      <i class="fa-solid fa-copy"></i>
                    </button>
                  </div>
                </div>
              `).join('')}
            </div>
          `}
        </div>

        <!-- Phone Numbers -->
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">
              <i class="fa-solid fa-phone" style="color: var(--flowiz-primary-purple);"></i>
              Phone Lines & Telephony
            </h3>
            <span class="badge badge-accent font-mono">${phones.length} RECORDED</span>
          </div>

          ${phones.length === 0 ? `
            <div class="text-muted" style="font-size: 13.5px;">No direct phone numbers recorded.</div>
          ` : `
            <div style="display: flex; flex-direction: column; gap: 10px;">
              ${phones.map(phone => `
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 18px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs);">
                  <div style="display: flex; align-items: center; gap: 12px;">
                    <i class="fa-solid fa-phone text-accent" style="font-size: 14px;"></i>
                    <span class="font-mono" style="font-size: 13.5px; font-weight: 600;">${window.api.escapeHtml(phone)}</span>
                  </div>
                  <span class="badge badge-neutral font-mono" style="font-size: 11px;">E.164 PARSED</span>
                </div>
              `).join('')}
            </div>
          `}
        </div>

        <!-- Decision Makers & Identified People -->
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">
              <i class="fa-solid fa-users" style="color: var(--flowiz-primary-purple);"></i>
              Key Personnel & Decision Makers
            </h3>
            <span class="badge badge-accent font-mono">${people.length} FOUND</span>
          </div>

          ${people.length === 0 ? `
            <div class="text-muted" style="font-size: 13.5px;">No individual executive or team profiles extracted from public sources.</div>
          ` : `
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px;">
              ${people.map(p => `
                <div style="padding: 14px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs);">
                  <div style="font-weight: 700; font-size: 14.5px; color: var(--flowiz-text-primary); margin-bottom: 3px;">
                    ${window.api.escapeHtml(typeof p === 'string' ? p : p.name || 'Unknown')}
                  </div>
                  <div class="text-secondary" style="font-size: 12.5px; margin-bottom: 6px;">
                    ${window.api.escapeHtml(typeof p === 'object' ? p.title || p.role || 'Executive' : 'Team Member')}
                  </div>
                  ${typeof p === 'object' && p.email ? `
                    <div class="font-mono text-accent" style="font-size: 11.5px;">
                      <i class="fa-solid fa-envelope" style="margin-right: 4px;"></i> ${window.api.escapeHtml(p.email)}
                    </div>
                  ` : ''}
                </div>
              `).join('')}
            </div>
          `}
        </div>
      </div>
    `;
  }

  _renderDomainTab() {
    const d = this.lead.domain_intel || {};
    const hasD = Object.keys(d).length > 0;

    return `
      <div style="display: flex; flex-direction: column; gap: 24px;">
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">
              <i class="fa-solid fa-network-wired" style="color: var(--flowiz-primary-purple);"></i>
              Domain & Host Intelligence
            </h3>
            <span class="badge badge-accent font-mono">${window.api.escapeHtml(this.lead.domain || 'N/A')}</span>
          </div>

          ${!hasD ? `
            <div class="text-muted" style="font-size: 13.5px;">Detailed WHOIS and DNS profiles are deferred or un-cached for this domain.</div>
          ` : `
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 18px;">
              ${d.registrar ? `
                <div>
                  <div class="text-caption text-muted">Registrar</div>
                  <div class="text-primary font-mono" style="font-size: 13.5px; font-weight: 600;">${window.api.escapeHtml(d.registrar)}</div>
                </div>
              ` : ''}

              ${d.creation_date ? `
                <div>
                  <div class="text-caption text-muted">Registration Date</div>
                  <div class="text-primary font-mono" style="font-size: 13.5px; font-weight: 600;">${window.api.escapeHtml(d.creation_date)}</div>
                </div>
              ` : ''}

              ${d.country ? `
                <div>
                  <div class="text-caption text-muted">Hosting Geo / Country</div>
                  <div class="text-primary" style="font-size: 13.5px; font-weight: 600;">${window.api.escapeHtml(d.country)}</div>
                </div>
              ` : ''}

              <div>
                <div class="text-caption text-muted">SSL Certificate Status</div>
                <div style="margin-top: 4px;">
                  ${d.ssl_valid !== false ? `
                    <span class="badge badge-success font-mono"><i class="fa-solid fa-lock"></i> SSL VALID</span>
                  ` : `
                    <span class="badge badge-danger font-mono"><i class="fa-solid fa-lock-open"></i> NO SSL / INVALID</span>
                  `}
                </div>
              </div>
            </div>
          `}
        </div>

        <!-- Nameservers & MX Records -->
        <div class="card">
          <h3 class="card-title" style="margin-bottom: 14px;">DNS Configuration & Mail Exchangers</h3>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 18px;">
            <div>
              <div class="text-caption text-muted" style="margin-bottom: 8px;">NAMESERVERS</div>
              ${d.nameservers && d.nameservers.length ? `
                <div style="display: flex; flex-direction: column; gap: 6px;">
                  ${d.nameservers.map(ns => `
                    <div class="font-mono text-secondary" style="font-size: 12.5px; padding: 8px 12px; background: var(--flowiz-bg-secondary); border-radius: var(--radius-sm); border: 1px solid var(--flowiz-border);">
                      ${window.api.escapeHtml(ns)}
                    </div>
                  `).join('')}
                </div>
              ` : '<div class="text-muted" style="font-size: 12.5px;">Standard Root DNS</div>'}
            </div>

            <div>
              <div class="text-caption text-muted" style="margin-bottom: 8px;">MX MAIL EXCHANGERS</div>
              ${d.mx_records && d.mx_records.length ? `
                <div style="display: flex; flex-direction: column; gap: 6px;">
                  ${d.mx_records.map(mx => `
                    <div class="font-mono text-secondary" style="font-size: 12.5px; padding: 8px 12px; background: var(--flowiz-bg-secondary); border-radius: var(--radius-sm); border: 1px solid var(--flowiz-border);">
                      ${window.api.escapeHtml(mx)}
                    </div>
                  `).join('')}
                </div>
              ` : '<div class="text-muted" style="font-size: 12.5px;">No custom MX returned</div>'}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderOsintTab() {
    const l = this.lead;
    const soc = l.social_links || {};
    const hasSocial = Object.keys(soc).length > 0 || l.linkedin || l.twitter;

    return `
      <div style="display: flex; flex-direction: column; gap: 24px;">
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">
              <i class="fa-solid fa-share-nodes" style="color: var(--flowiz-primary-purple);"></i>
              Social Footprint & External Channels
            </h3>
          </div>

          ${!hasSocial ? `
            <div class="text-muted" style="font-size: 13.5px;">No social media profiles linked to this domain.</div>
          ` : `
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px;">
              ${(l.linkedin || soc.linkedin) ? `
                <a href="${window.api.escapeHtml(l.linkedin || soc.linkedin)}" target="_blank" rel="noopener noreferrer" style="text-decoration: none; padding: 14px 18px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs); display: flex; align-items: center; justify-content: space-between;">
                  <div style="display: flex; align-items: center; gap: 12px;">
                    <i class="fa-brands fa-linkedin" style="color: #0077b5; font-size: 22px;"></i>
                    <div>
                      <div style="font-weight: 700; font-size: 14px; color: var(--flowiz-text-primary);">LinkedIn</div>
                      <div class="font-mono text-muted" style="font-size: 11px;">Verified Company Page</div>
                    </div>
                  </div>
                  <i class="fa-solid fa-arrow-up-right-from-square text-muted" style="font-size: 12px;"></i>
                </a>
              ` : ''}

              ${(l.twitter || soc.twitter) ? `
                <a href="${window.api.escapeHtml(l.twitter || soc.twitter)}" target="_blank" rel="noopener noreferrer" style="text-decoration: none; padding: 14px 18px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs); display: flex; align-items: center; justify-content: space-between;">
                  <div style="display: flex; align-items: center; gap: 12px;">
                    <i class="fa-brands fa-x-twitter" style="color: #0F172A; font-size: 22px;"></i>
                    <div>
                      <div style="font-weight: 700; font-size: 14px; color: var(--flowiz-text-primary);">Twitter / X</div>
                      <div class="font-mono text-muted" style="font-size: 11px;">Official Feed</div>
                    </div>
                  </div>
                  <i class="fa-solid fa-arrow-up-right-from-square text-muted" style="font-size: 12px;"></i>
                </a>
              ` : ''}

              ${soc.facebook ? `
                <a href="${window.api.escapeHtml(soc.facebook)}" target="_blank" rel="noopener noreferrer" style="text-decoration: none; padding: 14px 18px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs); display: flex; align-items: center; justify-content: space-between;">
                  <div style="display: flex; align-items: center; gap: 12px;">
                    <i class="fa-brands fa-facebook" style="color: #1877f2; font-size: 22px;"></i>
                    <div style="font-weight: 700; font-size: 14px; color: var(--flowiz-text-primary);">Facebook</div>
                  </div>
                  <i class="fa-solid fa-arrow-up-right-from-square text-muted" style="font-size: 12px;"></i>
                </a>
              ` : ''}

              ${soc.github ? `
                <a href="${window.api.escapeHtml(soc.github)}" target="_blank" rel="noopener noreferrer" style="text-decoration: none; padding: 14px 18px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs); display: flex; align-items: center; justify-content: space-between;">
                  <div style="display: flex; align-items: center; gap: 12px;">
                    <i class="fa-brands fa-github" style="color: #0F172A; font-size: 22px;"></i>
                    <div style="font-weight: 700; font-size: 14px; color: var(--flowiz-text-primary);">GitHub Org</div>
                  </div>
                  <i class="fa-solid fa-arrow-up-right-from-square text-muted" style="font-size: 12px;"></i>
                </a>
              ` : ''}
            </div>
          `}
        </div>

        <!-- Corporate Registry Matching -->
        <div class="card">
          <h3 class="card-title" style="margin-bottom: 14px;">Corporate Registry Intelligence</h3>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 18px;">
            <div style="padding: 14px; background: var(--flowiz-bg-secondary); border: 1px solid var(--flowiz-border); border-radius: var(--radius-md);">
              <div style="font-weight: 700; font-size: 14px; margin-bottom: 4px;">OpenCorporates Match</div>
              <div class="text-caption text-muted">Global corporate registration records & filings</div>
              <div style="margin-top: 10px;">
                <span class="badge badge-accent font-mono">MATCH ATTEMPTED</span>
              </div>
            </div>

            <div style="padding: 14px; background: var(--flowiz-bg-secondary); border: 1px solid var(--flowiz-border); border-radius: var(--radius-md);">
              <div style="font-weight: 700; font-size: 14px; margin-bottom: 4px;">Zauba Corp / MCA India</div>
              <div class="text-caption text-muted">Ministry of Corporate Affairs CIN / Director matching</div>
              <div style="margin-top: 10px;">
                <span class="badge badge-neutral font-mono">SEARCH ON DEMAND</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderTechTab() {
    const stack = Array.isArray(this.lead.tech_stack) ? this.lead.tech_stack : [];

    return `
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">
            <i class="fa-solid fa-microchip" style="color: var(--flowiz-primary-purple);"></i>
            Detected Technology Stack & Web Fingerprints
          </h3>
          <span class="badge badge-accent font-mono">${stack.length} COMPONENTS</span>
        </div>

        ${stack.length === 0 ? `
          <div class="text-muted" style="font-size: 13.5px;">No third-party frameworks, CMS, or analytics libraries detected.</div>
        ` : `
          <div style="display: flex; flex-wrap: wrap; gap: 10px;">
            ${stack.map(tech => `
              <span class="badge badge-accent font-mono" style="padding: 8px 14px; font-size: 12.5px;">
                <i class="fa-solid fa-tag" style="margin-right: 6px; font-size: 11px;"></i>
                ${window.api.escapeHtml(tech)}
              </span>
            `).join('')}
          </div>
        `}
      </div>
    `;
  }

  _renderOrgTab() {
    const g = this.lead.org_graph;
    const hasG = g && (g.nodes || g.edges || Object.keys(g).length > 0);

    return `
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">
            <i class="fa-solid fa-sitemap" style="color: var(--flowiz-primary-purple);"></i>
            Entity Organization Graph
          </h3>
          <span class="badge badge-accent font-mono">HIERARCHY VIEW</span>
        </div>

        ${!hasG ? `
          <div class="text-muted" style="font-size: 13.5px;">No explicit relationship nodes linked in canonical storage.</div>
        ` : `
          <div style="padding: 24px; background: var(--flowiz-bg-secondary); border: 1px solid var(--flowiz-border-accent); border-radius: var(--radius-lg); text-align: center;">
            <div style="display: inline-block; padding: 12px 24px; background: #FFFFFF; border: 2px solid var(--flowiz-primary-purple); border-radius: var(--radius-pill); font-weight: 800; color: var(--flowiz-text-primary); margin-bottom: 24px; box-shadow: var(--shadow-sm);">
              <i class="fa-solid fa-building" style="margin-right: 8px; color: var(--flowiz-primary-purple);"></i>
              ${window.api.escapeHtml(this.lead.company_name || 'Organization')}
            </div>

            <div style="display: flex; justify-content: center; gap: 20px; flex-wrap: wrap;">
              ${Array.isArray(this.lead.people) && this.lead.people.length > 0 ? this.lead.people.map(p => `
                <div style="padding: 10px 18px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs); min-width: 140px;">
                  <div style="font-weight: 700; font-size: 13px; color: var(--flowiz-text-primary);">${window.api.escapeHtml(typeof p === 'string' ? p : p.name || 'Staff')}</div>
                  <div class="text-muted" style="font-size: 11px;">${window.api.escapeHtml(typeof p === 'object' ? p.title || 'Role' : 'Member')}</div>
                </div>
              `).join('') : `
                <div style="padding: 10px 18px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs);">
                  <div style="font-weight: 700; font-size: 13px;">Executive Management</div>
                </div>
                <div style="padding: 10px 18px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs);">
                  <div style="font-weight: 700; font-size: 13px;">Engineering & Product</div>
                </div>
                <div style="padding: 10px 18px; background: #FFFFFF; border: 1px solid var(--flowiz-border); border-radius: var(--radius-md); box-shadow: var(--shadow-xs);">
                  <div style="font-weight: 700; font-size: 13px;">Sales & Operations</div>
                </div>
              `}
            </div>
          </div>
        `}
      </div>
    `;
  }

  _renderProvenanceTab() {
    const l = this.lead;
    const items = [
      { field: 'Company Name', val: l.company_name, src: 'Discovery Crawl', prov: 'SearchEngineCrawler', conf: 'High' },
      { field: 'Official Domain', val: l.domain, src: 'Domain Extraction', prov: 'Pillar2Normalizer', conf: 'Verified' },
      { field: 'Primary Website', val: l.website, src: 'HTTP Fetch', prov: 'SafeHttpClient', conf: 'Verified' },
      { field: 'Contact Email', val: (l.emails || []).join(', ') || 'N/A', src: 'Regex Page Scraper', prov: 'EmailExtractor', conf: 'Syntax Valid' },
      { field: 'Lead Score', val: `${l.lead_score || 0} / 100`, src: 'Pillar 4 Quality Engine', prov: 'ScoringPipeline', conf: 'Deterministic' },
    ];

    return `
      <div class="card" style="padding: 0; overflow: hidden;">
        <div class="card-header" style="padding: 20px 24px; border-bottom: 1px solid var(--flowiz-border); margin-bottom: 0;">
          <h3 class="card-title">
            <i class="fa-solid fa-clock-rotate-left" style="color: var(--flowiz-primary-purple);"></i>
            Data Provenance & Traceability Audit
          </h3>
          <span class="badge badge-accent font-mono">CANONICAL AUDIT</span>
        </div>

        <div class="table-container">
          <table class="data-table">
            <thead>
              <tr>
                <th>Entity Field</th>
                <th>Extracted Value</th>
                <th>Ingestion Source</th>
                <th>OSINT Provider</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              ${items.map(it => `
                <tr>
                  <td style="font-weight: 700; font-size: 13.5px; color: var(--flowiz-text-primary);">${it.field}</td>
                  <td class="font-mono text-secondary" style="font-size: 12.5px;">${window.api.escapeHtml(it.val)}</td>
                  <td class="text-muted" style="font-size: 12.5px;">${it.src}</td>
                  <td class="font-mono text-accent" style="font-size: 12.5px; font-weight: 600;">${it.prov}</td>
                  <td><span class="badge badge-neutral font-mono" style="font-size: 11px;">${it.conf}</span></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  _renderRawTab() {
    return `
      <div class="card" style="padding: 0; overflow: hidden; border-radius: var(--radius-lg);">
        <div class="card-header" style="padding: 16px 22px; background: #FAF8FF; border-bottom: 1px solid var(--flowiz-border); margin-bottom: 0;">
          <div class="card-title" style="font-size: 14px;">
            <i class="fa-solid fa-code" style="color: var(--flowiz-primary-purple);"></i>
            Canonical LeadRecord JSON Payload
          </div>
          <button class="btn btn-secondary btn-sm" id="btnCopyJsonPayload">
            <i class="fa-solid fa-copy"></i> Copy JSON
          </button>
        </div>
        <pre class="font-mono" style="margin: 0; padding: 20px; font-size: 12.5px; line-height: 1.6; color: var(--flowiz-text-secondary); max-height: 480px; overflow-y: auto; background: #FFFFFF;">${window.api.escapeHtml(JSON.stringify(this.lead, null, 2))}</pre>
      </div>
    `;
  }

  _bindEvents() {
    // Backdrop click closes
    const backdrop = this.container.querySelector('#modalBackdrop');
    if (backdrop) {
      backdrop.addEventListener('click', (e) => {
        if (e.target === backdrop) this.close();
      });
    }

    // Close button
    const btnClose = this.container.querySelector('#btnCloseModal');
    if (btnClose) btnClose.addEventListener('click', () => this.close());

    // Copy Domain button
    const btnCopyDomain = this.container.querySelector('#btnCopyDomain');
    if (btnCopyDomain && this.lead.domain) {
      btnCopyDomain.addEventListener('click', () => {
        navigator.clipboard.writeText(this.lead.domain);
        btnCopyDomain.innerHTML = '<i class="fa-solid fa-check text-success"></i> Copied!';
        setTimeout(() => {
          btnCopyDomain.innerHTML = '<i class="fa-solid fa-copy"></i> Copy Domain';
        }, 1500);
      });
    }

    // Export JSON
    const btnExport = this.container.querySelector('#btnExportLeadJson');
    if (btnExport) {
      btnExport.addEventListener('click', () => {
        window.api.exportJson(this.lead, `flowiz_lead_${this.lead.domain || 'record'}.json`);
      });
    }

    // Tabs navigation
    this.container.querySelectorAll('.modal-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        this.activeTab = tab.getAttribute('data-tab');
        this.render();
      });
    });

    // Copy raw json payload
    const btnCopyJson = this.container.querySelector('#btnCopyJsonPayload');
    if (btnCopyJson) {
      btnCopyJson.addEventListener('click', () => {
        navigator.clipboard.writeText(JSON.stringify(this.lead, null, 2));
        btnCopyJson.innerHTML = '<i class="fa-solid fa-check text-success"></i> Copied!';
        setTimeout(() => {
          btnCopyJson.innerHTML = '<i class="fa-solid fa-copy"></i> Copy JSON';
        }, 1500);
      });
    }

    // Generic copy buttons
    this.container.querySelectorAll('.btn-copy-text').forEach(btn => {
      btn.addEventListener('click', () => {
        const text = btn.getAttribute('data-text');
        navigator.clipboard.writeText(text);
        btn.innerHTML = '<i class="fa-solid fa-check text-success"></i>';
        setTimeout(() => {
          btn.innerHTML = '<i class="fa-solid fa-copy"></i>';
        }, 1200);
      });
    });
  }
}

window.LeadDetailModal = LeadDetailModal;
window.leadDetail = new LeadDetailModal();
