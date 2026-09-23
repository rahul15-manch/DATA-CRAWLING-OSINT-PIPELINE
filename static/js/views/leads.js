/**
 * Flowiz Intelligence Platform — Leads Management Table View
 * Redesigned with Light Pastel Futuristic Theme (flowiz.biz)
 */

class LeadsView {
  constructor() {
    this.container = null;
    this.sortField = 'lead_score';
    this.sortOrder = 'desc'; // 'asc' | 'desc'
  }

  render(container) {
    this.container = container;
    const paged = this._getPagedAndSortedLeads();
    const categories = Object.keys(window.state.categories);

    this.container.innerHTML = `
      <div class="view-header">
        <div>
          <div style="display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: var(--radius-pill); background: var(--flowiz-purple-badge-bg); border: 1px solid var(--flowiz-purple-badge-border); color: var(--flowiz-primary-purple-dark); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px;">
            <i class="fa-solid fa-address-book"></i> Verified Intelligence Database
          </div>
          <h1 class="view-title">Your Leads</h1>
          <div class="view-subtitle">
            Canonical database records with algorithmic quality scores and verified contact vectors.
          </div>
        </div>
        <div style="display: flex; gap: 10px;">
          <button class="btn btn-secondary btn-sm" id="btnExportCsv">
            <i class="fa-solid fa-file-csv"></i> Export CSV
          </button>
          <button class="btn btn-secondary btn-sm" id="btnExportJson">
            <i class="fa-solid fa-file-code"></i> Export JSON
          </button>
        </div>
      </div>

      <!-- Filter Controls Toolbar -->
      <div class="card" style="margin-bottom: 24px; padding: 18px 24px; border-radius: var(--radius-lg);">
        <div style="display: flex; flex-wrap: wrap; gap: 14px; align-items: center; justify-content: space-between;">
          <!-- Left: Search Filter -->
          <div style="display: flex; gap: 10px; flex: 1; min-width: 280px; max-width: 440px;">
            <div style="position: relative; width: 100%;">
              <input 
                type="text" 
                id="leadFilterSearch" 
                class="input input-sm font-mono" 
                placeholder="Filter by company, domain, or keyword..." 
                value="${window.api.escapeHtml(window.state.searchQuery || '')}"
                style="padding-left: 36px; border-radius: var(--radius-pill);"
              />
              <i class="fa-solid fa-magnifying-glass" style="position: absolute; left: 14px; top: 11px; color: var(--flowiz-text-muted); font-size: 12px;"></i>
            </div>
          </div>

          <!-- Middle: Category Dropdown & Quality Filter -->
          <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
            <select id="leadCategorySelect" class="select select-sm" style="min-width: 160px; border-radius: var(--radius-pill);">
              <option value="">All Industries (${window.state.allLeads.length})</option>
              ${categories.map(cat => `
                <option value="${window.api.escapeHtml(cat)}" ${window.state.activeCategory === cat ? 'selected' : ''}>
                  ${window.api.escapeHtml(cat)} (${window.state.categories[cat]})
                </option>
              `).join('')}
            </select>

            <select id="leadQualitySelect" class="select select-sm" style="border-radius: var(--radius-pill);">
              <option value="">All Qualities</option>
              <option value="High" ${window.state.activeQuality === 'High' ? 'selected' : ''}>High Quality</option>
              <option value="Medium" ${window.state.activeQuality === 'Medium' ? 'selected' : ''}>Medium Quality</option>
              <option value="Low" ${window.state.activeQuality === 'Low' ? 'selected' : ''}>Low Quality</option>
            </select>
          </div>

          <!-- Right: Checkbox Toggles -->
          <div style="display: flex; gap: 16px; align-items: center; font-size: 13px; color: var(--flowiz-text-secondary); font-weight: 500;">
            <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
              <input type="checkbox" id="chkHasEmail" ${window.state.filterHasEmail ? 'checked' : ''} />
              <span>Email</span>
            </label>
            <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
              <input type="checkbox" id="chkHasPhone" ${window.state.filterHasPhone ? 'checked' : ''} />
              <span>Phone</span>
            </label>
            <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
              <input type="checkbox" id="chkHasSocial" ${window.state.filterHasSocial ? 'checked' : ''} />
              <span>Social</span>
            </label>
          </div>
        </div>
      </div>

      <!-- Leads Data Table Card -->
      <div class="card" style="padding: 0; overflow: hidden; border-radius: var(--radius-lg);">
        <div class="table-container">
          <table class="data-table">
            <thead>
              <tr>
                <th class="th-sortable" data-sort="company_name">
                  Company ${this._renderSortIcon('company_name')}
                </th>
                <th class="th-sortable" data-sort="domain">
                  Domain ${this._renderSortIcon('domain')}
                </th>
                <th class="th-sortable" data-sort="industry">
                  Industry ${this._renderSortIcon('industry')}
                </th>
                <th>Location</th>
                <th class="th-sortable" data-sort="lead_score">
                  Lead Score ${this._renderSortIcon('lead_score')}
                </th>
                <th class="th-sortable" data-sort="lead_quality">
                  Quality ${this._renderSortIcon('lead_quality')}
                </th>
                <th>Verification</th>
                <th>Signals</th>
                <th style="text-align: right;">Action</th>
              </tr>
            </thead>
            <tbody>
              ${paged.items.length === 0 ? `
                <tr>
                  <td colspan="9" style="text-align: center; padding: 48px;">
                    <div class="empty-state">
                      <div class="empty-state-icon"><i class="fa-solid fa-filter-circle-xmark"></i></div>
                      <div class="empty-state-title">No Leads Match Selected Filters</div>
                      <div class="empty-state-description">Try adjusting your search criteria, industry category, or reset filters.</div>
                      <button class="btn btn-secondary btn-sm" id="btnResetLeadFilters">Clear Filters</button>
                    </div>
                  </td>
                </tr>
              ` : paged.items.map(lead => this._renderRow(lead)).join('')}
            </tbody>
          </table>
        </div>

        <!-- Table Footer / Pagination -->
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; border-top: 1px solid var(--flowiz-border-subtle); background: #FFFFFF;">
          <div class="text-caption text-muted">
            Showing <strong class="text-primary font-mono">${(paged.currentPage - 1) * window.state.pageSize + 1}</strong>
            to <strong class="text-primary font-mono">${Math.min(paged.currentPage * window.state.pageSize, paged.total)}</strong>
            of <strong class="text-primary font-mono">${paged.total}</strong> filtered records
            (from ${window.state.allLeads.length} total)
          </div>

          <div style="display: flex; gap: 8px; align-items: center;">
            <button class="btn btn-secondary btn-sm" id="btnPrevPage" ${paged.currentPage <= 1 ? 'disabled' : ''}>
              <i class="fa-solid fa-chevron-left"></i> Previous
            </button>
            <span class="text-caption font-mono" style="padding: 0 10px; font-weight: 600;">
              Page ${paged.currentPage} / ${paged.totalPages}
            </span>
            <button class="btn btn-secondary btn-sm" id="btnNextPage" ${paged.currentPage >= paged.totalPages ? 'disabled' : ''}>
              Next <i class="fa-solid fa-chevron-right"></i>
            </button>
          </div>
        </div>
      </div>
    `;

    this._bindEvents();
  }

  _renderSortIcon(field) {
    if (this.sortField !== field) {
      return '<i class="fa-solid fa-sort" style="color: var(--flowiz-text-muted); opacity: 0.4; font-size: 11px; margin-left: 4px;"></i>';
    }
    return this.sortOrder === 'asc' 
      ? '<i class="fa-solid fa-sort-up text-accent" style="font-size: 11px; margin-left: 4px;"></i>' 
      : '<i class="fa-solid fa-sort-down text-accent" style="font-size: 11px; margin-left: 4px;"></i>';
  }

  _getPagedAndSortedLeads() {
    let list = [...window.state.getFilteredLeads()];

    // Sorting
    list.sort((a, b) => {
      let va = a[this.sortField];
      let vb = b[this.sortField];

      if (this.sortField === 'lead_score') {
        va = Number(va) || 0;
        vb = Number(vb) || 0;
      } else {
        va = (va || '').toString().toLowerCase();
        vb = (vb || '').toString().toLowerCase();
      }

      if (va < vb) return this.sortOrder === 'asc' ? -1 : 1;
      if (va > vb) return this.sortOrder === 'asc' ? 1 : -1;
      return 0;
    });

    const start = (window.state.page - 1) * window.state.pageSize;
    return {
      items: list.slice(start, start + window.state.pageSize),
      total: list.length,
      totalPages: Math.ceil(list.length / window.state.pageSize) || 1,
      currentPage: window.state.page
    };
  }

  _renderRow(lead) {
    const q = (lead.lead_quality || 'Low').toLowerCase();
    const qBadge = q === 'high' ? 'badge-success' : q === 'medium' ? 'badge-warning' : 'badge-neutral';
    const hasEmail = Array.isArray(lead.emails) && lead.emails.length > 0;
    const hasPhone = Array.isArray(lead.phones) && lead.phones.length > 0;
    const hasSocial = lead.social_links && Object.keys(lead.social_links).length > 0;
    const isVerified = lead.verification_status === 'Verified' || hasEmail || hasPhone;

    return `
      <tr class="lead-row" data-domain="${window.api.escapeHtml(lead.domain || '')}" style="cursor: pointer;">
        <td style="font-weight: 700; color: var(--flowiz-text-primary);">
          ${window.api.escapeHtml(lead.company_name || 'Unknown')}
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
          <div style="display: flex; align-items: center; gap: 8px;">
            <div class="lead-score-gauge">
              ${lead.lead_score || 0}
            </div>
            <div class="progress-bar" style="width: 44px; height: 5px;">
              <div class="progress-fill" style="width: ${Math.min(100, lead.lead_score || 0)}%"></div>
            </div>
          </div>
        </td>
        <td>
          <span class="badge ${qBadge}">${window.api.escapeHtml(lead.lead_quality || 'Low')}</span>
        </td>
        <td>
          ${isVerified ? `
            <span class="badge badge-success" style="font-size: 11px;">
              <i class="fa-solid fa-check" style="font-size: 9px;"></i> Verified
            </span>
          ` : `
            <span class="badge badge-neutral" style="font-size: 11px;">
              Discovered
            </span>
          `}
        </td>
        <td>
          <div style="display: flex; gap: 8px; font-size: 13px;">
            ${hasEmail ? `<span title="${lead.emails[0]}" class="text-success"><i class="fa-solid fa-envelope"></i></span>` : '<span class="text-muted" style="opacity: 0.25"><i class="fa-solid fa-envelope"></i></span>'}
            ${hasPhone ? `<span title="${lead.phones[0]}" class="text-accent"><i class="fa-solid fa-phone"></i></span>` : '<span class="text-muted" style="opacity: 0.25"><i class="fa-solid fa-phone"></i></span>'}
            ${hasSocial ? `<span title="Social Presence Available" class="text-info"><i class="fa-solid fa-share-nodes"></i></span>` : '<span class="text-muted" style="opacity: 0.25"><i class="fa-solid fa-share-nodes"></i></span>'}
            ${lead.domain_intel ? `<span title="DNS / SSL Profiled" class="text-warning"><i class="fa-solid fa-shield-halved"></i></span>` : ''}
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
    // Search input
    const input = this.container.querySelector('#leadFilterSearch');
    if (input) {
      input.addEventListener('input', (e) => {
        window.state.searchQuery = e.target.value;
        window.state.page = 1;
        this.render(this.container);
      });
    }

    // Category select
    const catSel = this.container.querySelector('#leadCategorySelect');
    if (catSel) {
      catSel.addEventListener('change', (e) => {
        window.state.activeCategory = e.target.value || null;
        window.state.page = 1;
        this.render(this.container);
      });
    }

    // Quality select
    const qSel = this.container.querySelector('#leadQualitySelect');
    if (qSel) {
      qSel.addEventListener('change', (e) => {
        window.state.activeQuality = e.target.value || null;
        window.state.page = 1;
        this.render(this.container);
      });
    }

    // Checkboxes
    const chkEmail = this.container.querySelector('#chkHasEmail');
    const chkPhone = this.container.querySelector('#chkHasPhone');
    const chkSocial = this.container.querySelector('#chkHasSocial');

    if (chkEmail) chkEmail.addEventListener('change', (e) => {
      window.state.filterHasEmail = e.target.checked;
      window.state.page = 1;
      this.render(this.container);
    });
    if (chkPhone) chkPhone.addEventListener('change', (e) => {
      window.state.filterHasPhone = e.target.checked;
      window.state.page = 1;
      this.render(this.container);
    });
    if (chkSocial) chkSocial.addEventListener('change', (e) => {
      window.state.filterHasSocial = e.target.checked;
      window.state.page = 1;
      this.render(this.container);
    });

    // Reset filters
    const btnReset = this.container.querySelector('#btnResetLeadFilters');
    if (btnReset) {
      btnReset.addEventListener('click', () => {
        window.state.searchQuery = '';
        window.state.activeCategory = null;
        window.state.activeQuality = null;
        window.state.filterHasEmail = false;
        window.state.filterHasPhone = false;
        window.state.filterHasSocial = false;
        window.state.page = 1;
        this.render(this.container);
      });
    }

    // Sort headers
    this.container.querySelectorAll('.th-sortable').forEach(th => {
      th.addEventListener('click', () => {
        const field = th.getAttribute('data-sort');
        if (this.sortField === field) {
          this.sortOrder = this.sortOrder === 'asc' ? 'desc' : 'asc';
        } else {
          this.sortField = field;
          this.sortOrder = 'desc';
        }
        this.render(this.container);
      });
    });

    // Pagination buttons
    const btnPrev = this.container.querySelector('#btnPrevPage');
    const btnNext = this.container.querySelector('#btnNextPage');
    if (btnPrev) {
      btnPrev.addEventListener('click', () => {
        if (window.state.page > 1) {
          window.state.page--;
          this.render(this.container);
        }
      });
    }
    if (btnNext) {
      btnNext.addEventListener('click', () => {
        window.state.page++;
        this.render(this.container);
      });
    }

    // Export buttons
    const btnCsv = this.container.querySelector('#btnExportCsv');
    const btnJson = this.container.querySelector('#btnExportJson');
    if (btnCsv) {
      btnCsv.addEventListener('click', () => {
        window.api.exportCsv(window.state.getFilteredLeads());
      });
    }
    if (btnJson) {
      btnJson.addEventListener('click', () => {
        window.api.exportJson(window.state.getFilteredLeads());
      });
    }

    // Dossier inspector click
    this.container.querySelectorAll('.lead-row, .btn-inspect').forEach(el => {
      el.addEventListener('click', (e) => {
        const domain = el.getAttribute('data-domain');
        const targetLead = window.state.allLeads.find(l => l.domain === domain);
        if (targetLead) {
          window.state.setSelectedLead(targetLead, 'overview');
        }
      });
    });
  }
}

window.LeadsView = LeadsView;
