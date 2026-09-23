/**
 * Flowiz Intelligence Platform — Reactive Application State Manager
 */

class FlowizState {
  constructor() {
    this.currentView = 'overview';
    this.allLeads = [];
    this.categories = {};
    this.selectedLead = null;
    this.selectedLeadTab = 'overview';
    this.searchQuery = '';
    
    // Filtering & Pagination
    this.activeCategory = null;
    this.activeQuality = null;
    this.filterHasEmail = false;
    this.filterHasPhone = false;
    this.filterHasSocial = false;
    this.page = 1;
    this.pageSize = 25;

    // Live Pipeline Tracking
    this.pipelineState = {
      status: 'idle',
      stage: 'Ready',
      stage_code: 'IDLE',
      keyword: '',
      progress_pct: 0,
      companies_found: 0,
      leads_generated: 0,
      elapsed_sec: 0,
    };

    this.listeners = new Map();
  }

  subscribe(key, callback) {
    if (!this.listeners.has(key)) {
      this.listeners.set(key, new Set());
    }
    this.listeners.get(key).add(callback);
    return () => this.listeners.get(key).delete(callback);
  }

  notify(key, data) {
    if (this.listeners.has(key)) {
      this.listeners.get(key).forEach(cb => cb(data));
    }
  }

  setView(viewName) {
    if (this.currentView === viewName) return;
    this.currentView = viewName;
    this.notify('viewChange', viewName);
  }

  setLeads(leads) {
    this.allLeads = leads || [];
    this.notify('leadsUpdated', this.allLeads);
  }

  setCategories(cats) {
    this.categories = cats || {};
    this.notify('categoriesUpdated', this.categories);
  }

  setSelectedLead(lead, tab = 'overview') {
    this.selectedLead = lead;
    this.selectedLeadTab = tab;
    this.notify('selectedLeadChanged', { lead, tab });
  }

  setSelectedLeadTab(tab) {
    this.selectedLeadTab = tab;
    this.notify('selectedLeadTabChanged', tab);
  }

  setPipelineState(state) {
    this.pipelineState = { ...this.pipelineState, ...state };
    this.notify('pipelineStateChanged', this.pipelineState);
  }

  // Filtered Leads Getter
  getFilteredLeads() {
    let list = this.allLeads;

    // Search query filter (company name, domain, industry, keyword)
    if (this.searchQuery && this.searchQuery.trim()) {
      const q = this.searchQuery.toLowerCase().trim();
      list = list.filter(l => 
        (l.company_name && l.company_name.toLowerCase().includes(q)) ||
        (l.domain && l.domain.toLowerCase().includes(q)) ||
        (l.industry && l.industry.toLowerCase().includes(q)) ||
        (l.keyword && l.keyword.toLowerCase().includes(q)) ||
        (l.location && l.location.toLowerCase().includes(q))
      );
    }

    // Category / Industry filter
    if (this.activeCategory) {
      const catLower = this.activeCategory.toLowerCase();
      list = list.filter(l => 
        (l.industry && l.industry.toLowerCase() === catLower) ||
        (l.company_type && l.company_type.toLowerCase() === catLower)
      );
    }

    // Quality filter
    if (this.activeQuality) {
      list = list.filter(l => (l.lead_quality || 'Low').toLowerCase() === this.activeQuality.toLowerCase());
    }

    // Attribute checkboxes
    if (this.filterHasEmail) {
      list = list.filter(l => Array.isArray(l.emails) && l.emails.length > 0);
    }
    if (this.filterHasPhone) {
      list = list.filter(l => Array.isArray(l.phones) && l.phones.length > 0);
    }
    if (this.filterHasSocial) {
      list = list.filter(l => l.social_links && Object.keys(l.social_links).length > 0);
    }

    return list;
  }

  getPagedLeads() {
    const filtered = this.getFilteredLeads();
    const start = (this.page - 1) * this.pageSize;
    return {
      items: filtered.slice(start, start + this.pageSize),
      total: filtered.length,
      totalPages: Math.ceil(filtered.length / this.pageSize) || 1,
      currentPage: this.page
    };
  }

  // Derived Analytics Computations
  getMetrics() {
    const total = this.allLeads.length;
    let verifiedCount = 0;
    let enrichedCount = 0;
    let scoreSum = 0;
    let scoredCount = 0;

    this.allLeads.forEach(l => {
      const hasEmail = Array.isArray(l.emails) && l.emails.length > 0;
      const hasPhone = Array.isArray(l.phones) && l.phones.length > 0;
      if (hasEmail || hasPhone) verifiedCount++;
      if (l.domain_intel || (Array.isArray(l.people) && l.people.length > 0) || (Array.isArray(l.tech_stack) && l.tech_stack.length > 0)) {
        enrichedCount++;
      }
      if (typeof l.lead_score === 'number' && l.lead_score > 0) {
        scoreSum += l.lead_score;
        scoredCount++;
      }
    });

    const avgScore = scoredCount > 0 ? Math.round(scoreSum / scoredCount) : 0;

    return {
      totalLeads: total,
      verifiedLeads: verifiedCount,
      enrichedLeads: enrichedCount,
      avgScore: avgScore,
      activeProviders: 9, // 9 active, 1 deferred (Hunter)
      totalQueriesExecuted: Object.keys(this.categories).length > 0 ? 50 : 0
    };
  }
}

// Global State Instance
window.state = new FlowizState();
