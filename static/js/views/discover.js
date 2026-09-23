/**
 * Flowiz Intelligence Platform — Discover Workspace View
 * Redesigned with Light Pastel Futuristic Theme (flowiz.biz)
 */

class DiscoverView {
  constructor() {
    this.container = null;
    this.activeFamily = 'company';
    this.viewMode = 'grid'; // 'grid' | 'list'
  }

  render(container) {
    this.container = container;
    const pipe = window.state.pipelineState;
    const matchingLeads = this._getMatchingLeads();

    this.container.innerHTML = `
      <!-- Hero Section -->
      <div style="margin-bottom: 28px; text-align: center; max-width: 800px; margin-left: auto; margin-right: auto;">
        <div style="display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: var(--radius-pill); background: var(--flowiz-purple-badge-bg); border: 1px solid var(--flowiz-purple-badge-border); color: var(--flowiz-primary-purple-dark); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 12px;">
          <i class="fa-solid fa-radar"></i> Deep Web & OSINT Discovery
        </div>
        <h1 style="font-size: 34px; font-weight: 800; line-height: 1.2; letter-spacing: -0.03em; margin: 0 0 10px 0; color: var(--flowiz-text-primary);">
          Discover Business Intelligence <span class="text-gradient">with AI</span>
        </h1>
        <div class="text-secondary" style="font-size: 15px; line-height: 1.6;">
          Search, enrich, verify and understand organizations from a single intelligence workspace.
        </div>
      </div>

      <!-- Main Search Box Card -->
      <div class="card" style="margin-bottom: 28px; padding: 28px; border-radius: var(--radius-xl); box-shadow: var(--shadow-lg);">
        <div style="margin-bottom: 20px;">
          <div style="display: flex; gap: 12px; flex-wrap: wrap;">
            <div style="position: relative; flex: 1; min-width: 280px;">
              <input 
                type="text" 
                id="discoverSearchInput" 
                class="input font-mono" 
                placeholder="What are you looking for? e.g. automation companies in India, robotics AI"
                value="${window.api.escapeHtml(window.state.searchQuery || '')}"
                style="height: 52px; font-size: 15px; padding-left: 48px; border-radius: var(--radius-pill);"
              />
              <i class="fa-solid fa-magnifying-glass" style="position: absolute; left: 18px; top: 18px; color: var(--flowiz-primary-purple); font-size: 16px;"></i>
            </div>
            <button class="btn btn-primary btn-lg" id="btnLaunchDiscovery" style="padding: 0 32px; border-radius: var(--radius-pill);">
              <span>Start Discovery</span>
              <i class="fa-solid fa-arrow-up-right-from-square" style="font-size: 12px;"></i>
            </button>
          </div>
        </div>

        <!-- Query Family Pills -->
        <div style="margin-bottom: 18px;">
          <div style="font-size: 12px; color: var(--flowiz-text-muted); margin-bottom: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">
            TARGET QUERY FAMILY (M5 RETRIEVAL ORCHESTRATION):
          </div>
          <div style="display: flex; flex-wrap: wrap; gap: 8px;">
            ${this._renderFamilyPill('company', 'Company / Market', 'fa-building')}
            ${this._renderFamilyPill('contact', 'Contact Discovery', 'fa-address-book')}
            ${this._renderFamilyPill('leadership', 'Leadership & Team', 'fa-users-gear')}
            ${this._renderFamilyPill('careers', 'Careers & Hiring', 'fa-briefcase')}
            ${this._renderFamilyPill('documents', 'Public Documents', 'fa-file-pdf')}
            ${this._renderFamilyPill('registry', 'Corporate Registry', 'fa-landmark')}
            ${this._renderFamilyPill('social', 'Social Footprint', 'fa-share-nodes')}
          </div>
        </div>

        <!-- Advanced Dork Chips & Shortcuts -->
        <div style="padding-top: 16px; border-top: 1px solid var(--flowiz-border-subtle); display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;">
          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
            <span style="font-size: 11px; text-transform: uppercase; color: var(--flowiz-text-muted); font-weight: 700;">Dork Templates:</span>
            <button class="badge badge-neutral font-mono dork-chip" data-dork='site:.com inurl:contact "email"'>site:.com inurl:contact "email"</button>
            <button class="badge badge-neutral font-mono dork-chip" data-dork='intitle:"leadership" OR intitle:"team"'>intitle:"leadership"</button>
            <button class="badge badge-neutral font-mono dork-chip" data-dork='filetype:pdf "annual report" OR "company overview"'>filetype:pdf</button>
            <button class="badge badge-neutral font-mono dork-chip" data-dork='"automation" "Bangalore" "directors"'>"automation" "Bangalore"</button>
          </div>
          <button class="btn btn-secondary btn-sm" id="btnToggleAdvancedSearch">
            <i class="fa-solid fa-sliders"></i> Advanced Filters
          </button>
        </div>

        <!-- Collapsible Advanced Search Filters -->
        <div id="advancedSearchPanel" style="display: none; margin-top: 18px; padding-top: 18px; border-top: 1px dashed var(--flowiz-border);">
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px;">
            <div>
              <label class="text-caption text-muted" style="margin-bottom: 6px; display: block; font-weight: 600;">Location / Geography</label>
              <input type="text" id="advLocation" class="input input-sm" placeholder="e.g. San Jose, CA or India" />
            </div>
            <div>
              <label class="text-caption text-muted" style="margin-bottom: 6px; display: block; font-weight: 600;">Specific Domain Filter</label>
              <input type="text" id="advDomain" class="input input-sm font-mono" placeholder="e.g. automationanywhere.com" />
            </div>
            <div>
              <label class="text-caption text-muted" style="margin-bottom: 6px; display: block; font-weight: 600;">Industry Classification</label>
              <input type="text" id="advIndustry" class="input input-sm" placeholder="e.g. Robotics, SaaS" />
            </div>
            <div>
              <label class="text-caption text-muted" style="margin-bottom: 6px; display: block; font-weight: 600;">Target Result Limit</label>
              <select id="advLimit" class="select select-sm font-mono">
                <option value="5">5 targets (Fast verification)</option>
                <option value="10" selected>10 targets (Balanced)</option>
                <option value="25">25 targets (Deep crawl)</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      <!-- Live Execution Telemetry Card -->
      <div class="card" id="pipelineProgressCard" style="margin-bottom: 28px; background: var(--flowiz-bg-secondary); border-color: var(--flowiz-primary-purple); ${pipe.status === 'running' ? '' : 'display: none;'}">
        <div class="card-header">
          <div style="display: flex; align-items: center; gap: 10px;">
            <span class="status-indicator status-indicator-running"></span>
            <h3 class="card-title">Live Pipeline Execution</h3>
            <span class="badge badge-accent font-mono" id="pipelineActiveKeyword">"${window.api.escapeHtml(pipe.keyword)}"</span>
          </div>
          <span class="badge badge-neutral font-mono" id="pipelineStageBadge">${pipe.stage}</span>
        </div>

        <div class="progress-bar" style="height: 8px; margin-bottom: 14px;">
          <div class="progress-fill" id="pipelineProgressFill" style="width: ${pipe.progress_pct}%"></div>
        </div>

        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; font-size: 13px;">
          <div class="card" style="padding: 12px 16px; background: #FFFFFF;">
            <div class="text-muted" style="font-size: 11px; font-weight: 700;">CURRENT STAGE</div>
            <div style="font-weight: 700; color: var(--flowiz-text-primary); margin-top: 2px;" id="pipelineStageText">${pipe.stage}</div>
          </div>
          <div class="card" style="padding: 12px 16px; background: #FFFFFF;">
            <div class="text-muted" style="font-size: 11px; font-weight: 700;">TARGETS IDENTIFIED</div>
            <div style="font-weight: 800; font-size: 16px; margin-top: 2px;" class="font-mono text-accent" id="pipelineFoundText">${pipe.companies_found}</div>
          </div>
          <div class="card" style="padding: 12px 16px; background: #FFFFFF;">
            <div class="text-muted" style="font-size: 11px; font-weight: 700;">CANONICAL LEADS</div>
            <div style="font-weight: 800; font-size: 16px; margin-top: 2px;" class="font-mono text-success" id="pipelineLeadsText">${pipe.leads_generated}</div>
          </div>
          <div class="card" style="padding: 12px 16px; background: #FFFFFF;">
            <div class="text-muted" style="font-size: 11px; font-weight: 700;">ELAPSED RUNTIME</div>
            <div style="font-weight: 800; font-size: 16px; margin-top: 2px;" class="font-mono" id="pipelineElapsedText">${pipe.elapsed_sec}s</div>
          </div>
        </div>
      </div>

      <!-- Results Section -->
      <div class="card">
        <div class="card-header">
          <div>
            <h3 class="card-title">
              <i class="fa-solid fa-list-check" style="color: var(--flowiz-primary-purple);"></i>
              Discovered Entities Matching Query
            </h3>
            <div class="card-subtitle">
              Showing ${matchingLeads.length} canonical records matching current query context
            </div>
          </div>
          <div style="display: flex; gap: 8px;">
            <div style="display: flex; border: 1px solid var(--flowiz-border); border-radius: var(--radius-pill); overflow: hidden; padding: 2px; background: #FFFFFF;">
              <button class="btn btn-sm ${this.viewMode === 'grid' ? 'btn-primary' : 'btn-secondary'}" id="btnModeGrid" style="border: none; border-radius: var(--radius-pill); padding: 4px 12px;">
                <i class="fa-solid fa-grip"></i>
              </button>
              <button class="btn btn-sm ${this.viewMode === 'list' ? 'btn-primary' : 'btn-secondary'}" id="btnModeList" style="border: none; border-radius: var(--radius-pill); padding: 4px 12px;">
                <i class="fa-solid fa-list"></i>
              </button>
            </div>
          </div>
        </div>

        ${matchingLeads.length === 0 ? `
          <div class="empty-state">
            <div class="empty-state-icon"><i class="fa-solid fa-magnifying-glass-location"></i></div>
            <div class="empty-state-title">Nothing here yet</div>
            <div class="empty-state-description">
              Start your first discovery to begin building your intelligence workspace, or clear query filters to inspect the 218 pre-indexed leads.
            </div>
            <button class="btn btn-secondary" id="btnResetDiscoverQuery">Show All Discovered Leads</button>
          </div>
        ` : this.viewMode === 'grid' ? this._renderGrid(matchingLeads) : this._renderList(matchingLeads)}
      </div>
    `;

    this._bindEvents();
  }

  _renderFamilyPill(id, label, icon) {
    const active = this.activeFamily === id;
    return `
      <button class="btn btn-sm ${active ? 'btn-primary' : 'btn-secondary'} family-pill" data-family="${id}" style="font-size: 12px; border-radius: var(--radius-pill);">
        <i class="fa-solid ${icon}"></i> ${label}
      </button>
    `;
  }

  _getMatchingLeads() {
    return window.state.getFilteredLeads();
  }

  _renderGrid(leads) {
    return `
      <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; margin-top: 14px;">
        ${leads.map(lead => {
          const q = (lead.lead_quality || 'Low').toLowerCase();
          const qBadge = q === 'high' ? 'badge-success' : q === 'medium' ? 'badge-warning' : 'badge-neutral';
          const hasEmail = Array.isArray(lead.emails) && lead.emails.length > 0;
          const hasPhone = Array.isArray(lead.phones) && lead.phones.length > 0;
          const hasSocial = lead.social_links && Object.keys(lead.social_links).length > 0;

          return `
            <div class="card lead-card-item" data-domain="${window.api.escapeHtml(lead.domain || '')}" style="cursor: pointer; padding: 22px; border-radius: var(--radius-lg);">
              <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
                <div>
                  <div style="font-weight: 800; font-size: 16px; color: var(--flowiz-text-primary); margin-bottom: 2px;">
                    ${window.api.escapeHtml(lead.company_name || 'Unknown')}
                  </div>
                  <div class="font-mono text-accent" style="font-size: 12.5px; font-weight: 600;">
                    ${window.api.escapeHtml(lead.domain || '—')}
                  </div>
                </div>
                <span class="badge ${qBadge}">${window.api.escapeHtml(lead.lead_quality || 'Low')}</span>
              </div>

              <div class="text-secondary" style="font-size: 13px; line-height: 1.5; margin-bottom: 16px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; min-height: 38px;">
                ${window.api.escapeHtml(lead.description || 'No description available for this entity.')}
              </div>

              <div style="display: flex; justify-content: space-between; align-items: center; padding-top: 12px; border-top: 1px solid var(--flowiz-border-subtle); font-size: 12.5px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                  <span class="text-muted">Score:</span>
                  <span class="lead-score-gauge" style="width: 28px; height: 28px; font-size: 11px;">
                    ${lead.lead_score || 0}
                  </span>
                </div>
                <div style="display: flex; gap: 8px;">
                  ${hasEmail ? '<span class="text-success" title="Email Available"><i class="fa-solid fa-envelope"></i></span>' : ''}
                  ${hasPhone ? '<span class="text-accent" title="Phone Available"><i class="fa-solid fa-phone"></i></span>' : ''}
                  ${hasSocial ? '<span class="text-info" title="Social Profiles"><i class="fa-solid fa-share-nodes"></i></span>' : ''}
                </div>
              </div>
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  _renderList(leads) {
    return `
      <div class="table-container" style="margin-top: 14px;">
        <table class="data-table">
          <thead>
            <tr>
              <th>Target Entity</th>
              <th>Domain</th>
              <th>Industry</th>
              <th>Quality</th>
              <th>Score</th>
              <th style="text-align: right;">Action</th>
            </tr>
          </thead>
          <tbody>
            ${leads.map(lead => {
              const q = (lead.lead_quality || 'Low').toLowerCase();
              const qBadge = q === 'high' ? 'badge-success' : q === 'medium' ? 'badge-warning' : 'badge-neutral';
              return `
                <tr class="lead-row" data-domain="${window.api.escapeHtml(lead.domain || '')}" style="cursor: pointer;">
                  <td style="font-weight: 700; color: var(--flowiz-text-primary);">${window.api.escapeHtml(lead.company_name || 'Unknown')}</td>
                  <td class="font-mono text-accent" style="font-weight: 600;">${window.api.escapeHtml(lead.domain || '—')}</td>
                  <td>${window.api.escapeHtml(lead.industry || lead.company_type || 'Technology')}</td>
                  <td><span class="badge ${qBadge}">${window.api.escapeHtml(lead.lead_quality || 'Low')}</span></td>
                  <td>
                    <span class="lead-score-gauge" style="width: 28px; height: 28px; font-size: 11px;">${lead.lead_score || 0}</span>
                  </td>
                  <td style="text-align: right;">
                    <button class="btn btn-secondary btn-sm btn-inspect" data-domain="${window.api.escapeHtml(lead.domain || '')}">
                      <i class="fa-solid fa-id-card"></i> Dossier ↗
                    </button>
                  </td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  _bindEvents() {
    const input = this.container.querySelector('#discoverSearchInput');
    const btnLaunch = this.container.querySelector('#btnLaunchDiscovery');

    if (btnLaunch && input) {
      btnLaunch.addEventListener('click', async () => {
        const query = input.value.trim();
        if (!query) {
          alert('Please enter a query or target keyword.');
          return;
        }

        btnLaunch.disabled = true;
        btnLaunch.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Initializing Pipeline...';

        try {
          await window.api.startSearch(query);
          window.state.setPipelineState({
            status: 'running',
            stage: 'P1_SEARCH',
            keyword: query,
            progress_pct: 10,
          });

          // Show progress card immediately
          const pCard = this.container.querySelector('#pipelineProgressCard');
          if (pCard) pCard.style.display = 'block';

          // Begin polling live status
          window.api.pollStatus(
            (statusData) => {
              window.state.setPipelineState(statusData);
              this._updateProgressUI(statusData);
            },
            async (finalState) => {
              btnLaunch.disabled = false;
              btnLaunch.innerHTML = '<span>Start Discovery</span> <i class="fa-solid fa-arrow-up-right-from-square" style="font-size: 12px;"></i>';
              // Refresh leads from DB
              const updatedLeads = await window.api.getAllLeads();
              window.state.setLeads(updatedLeads);
              this.render(this.container);
            }
          );
        } catch (err) {
          alert(`Pipeline launch failed: ${err.message}`);
          btnLaunch.disabled = false;
          btnLaunch.innerHTML = '<span>Start Discovery</span> <i class="fa-solid fa-arrow-up-right-from-square" style="font-size: 12px;"></i>';
        }
      });
    }

    // Enter key triggers search
    if (input) {
      input.addEventListener('keyup', (e) => {
        if (e.key === 'Enter') {
          btnLaunch.click();
        } else {
          window.state.searchQuery = input.value;
        }
      });
    }

    // Family pills
    this.container.querySelectorAll('.family-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        this.activeFamily = pill.getAttribute('data-family');
        this.render(this.container);
      });
    });

    // Dork chips
    this.container.querySelectorAll('.dork-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const dork = chip.getAttribute('data-dork');
        if (input) {
          input.value = `${input.value ? input.value + ' ' : ''}${dork}`;
          input.focus();
        }
      });
    });

    // Advanced search toggle
    const btnAdv = this.container.querySelector('#btnToggleAdvancedSearch');
    const pnlAdv = this.container.querySelector('#advancedSearchPanel');
    if (btnAdv && pnlAdv) {
      btnAdv.addEventListener('click', () => {
        const isHidden = pnlAdv.style.display === 'none';
        pnlAdv.style.display = isHidden ? 'block' : 'none';
      });
    }

    // View mode switchers
    const btnGrid = this.container.querySelector('#btnModeGrid');
    const btnList = this.container.querySelector('#btnModeList');
    if (btnGrid && btnList) {
      btnGrid.addEventListener('click', () => {
        this.viewMode = 'grid';
        this.render(this.container);
      });
      btnList.addEventListener('click', () => {
        this.viewMode = 'list';
        this.render(this.container);
      });
    }

    // Reset button
    const btnReset = this.container.querySelector('#btnResetDiscoverQuery');
    if (btnReset) {
      btnReset.addEventListener('click', () => {
        window.state.searchQuery = '';
        if (input) input.value = '';
        this.render(this.container);
      });
    }

    // Card & Row clicks to open Dossier
    this.container.querySelectorAll('.lead-card-item, .lead-row').forEach(el => {
      el.addEventListener('click', () => {
        const domain = el.getAttribute('data-domain');
        const targetLead = window.state.allLeads.find(l => l.domain === domain);
        if (targetLead) {
          window.state.setSelectedLead(targetLead, 'overview');
        }
      });
    });

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
  }

  _updateProgressUI(pipe) {
    const fill = this.container.querySelector('#pipelineProgressFill');
    const stageBadge = this.container.querySelector('#pipelineStageBadge');
    const stageText = this.container.querySelector('#pipelineStageText');
    const foundText = this.container.querySelector('#pipelineFoundText');
    const leadsText = this.container.querySelector('#pipelineLeadsText');
    const elapsedText = this.container.querySelector('#pipelineElapsedText');

    if (fill) fill.style.width = `${pipe.progress_pct}%`;
    if (stageBadge) stageBadge.textContent = pipe.stage;
    if (stageText) stageText.textContent = pipe.stage;
    if (foundText) foundText.textContent = pipe.companies_found;
    if (leadsText) leadsText.textContent = pipe.leads_generated;
    if (elapsedText) elapsedText.textContent = `${pipe.elapsed_sec}s`;
  }
}

window.DiscoverView = DiscoverView;
