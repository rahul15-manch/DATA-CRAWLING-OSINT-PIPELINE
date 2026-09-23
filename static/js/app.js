/**
 * Flowiz Intelligence Platform — Main Application Coordinator
 */

class FlowizApp {
  constructor() {
    this.viewContainer = null;
    this.views = {};
  }

  async init() {
    this.viewContainer = document.getElementById('viewContainer');
    if (!this.viewContainer) {
      console.error('viewContainer element not found');
      return;
    }

    // Instantiate Views
    this.views = {
      overview: new window.OverviewView(),
      discover: new window.DiscoverView(),
      leads: new window.LeadsView(),
      searchIntel: new window.SearchIntelView(),
      osint: new window.OsintView(),
      pipeline: new window.PipelineView(),
      analytics: new window.AnalyticsView(),
      health: new window.HealthView(),
      settings: new window.SettingsView(),
    };

    // Wire State Subscriptions
    window.state.subscribe('viewChange', (viewName) => {
      this.renderView(viewName);
      this.updateSidebarUI(viewName);
      this.updateBreadcrumbs(viewName);
    });

    window.state.subscribe('leadsUpdated', () => {
      // Re-render current view if active
      if (this.views[window.state.currentView]) {
        this.views[window.state.currentView].render(this.viewContainer);
      }
      this.updateLeadCountBadge();
    });

    window.state.subscribe('selectedLeadChanged', ({ lead, tab }) => {
      if (lead) {
        window.leadDetail.show(lead, tab);
      } else {
        window.leadDetail.close();
      }
    });

    window.state.subscribe('pipelineStateChanged', (pipe) => {
      this.updateStatusPill(pipe);
    });

    // Wire Global Event Listeners
    this.bindGlobalEvents();

    // Bootstrap Initial Data from FastAPI Backend
    await this.bootstrapData();

    // Render Initial View
    this.renderView(window.state.currentView);
    this.updateSidebarUI(window.state.currentView);
    this.updateBreadcrumbs(window.state.currentView);
  }

  async bootstrapData() {
    try {
      // Load All Verified Leads
      const leads = await window.api.getAllLeads();
      window.state.setLeads(leads);

      // Load Categories breakdown
      const cats = await window.api.getCategories();
      window.state.setCategories(cats);

      // Load Current Pipeline Status
      const status = await window.api.getStatus();
      window.state.setPipelineState(status);
    } catch (err) {
      console.error('Failed to bootstrap initial data:', err);
    }
  }

  renderView(viewName) {
    const view = this.views[viewName] || this.views.overview;
    this.viewContainer.innerHTML = '';
    view.render(this.viewContainer);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  updateSidebarUI(viewName) {
    document.querySelectorAll('.sidebar-link').forEach(link => {
      const target = link.getAttribute('data-view');
      if (target === viewName) {
        link.classList.add('active');
      } else {
        link.classList.remove('active');
      }
    });
  }

  updateBreadcrumbs(viewName) {
    const names = {
      overview: 'Overview Dashboard',
      discover: 'Discover Intelligence',
      leads: 'Leads Management',
      searchIntel: 'Search Intelligence (M5)',
      osint: 'OSINT Provider Registry',
      pipeline: 'Pipeline Monitor',
      analytics: 'Analytics & Distributions',
      health: 'System Health',
      settings: 'Settings & Config',
    };
    const breadcrumbEl = document.getElementById('currentBreadcrumb');
    if (breadcrumbEl) {
      breadcrumbEl.textContent = names[viewName] || 'Dashboard';
    }
  }

  updateLeadCountBadge() {
    const badge = document.getElementById('sidebarLeadCount');
    if (badge) {
      badge.textContent = window.state.allLeads.length;
    }
  }

  updateStatusPill(pipe) {
    const pill = document.getElementById('topbarStatusPill');
    if (!pill) return;

    if (pipe.status === 'running') {
      pill.innerHTML = `
        <span class="status-indicator status-indicator-running"></span>
        <span class="font-mono" style="font-size: 11px;">RUNNING: ${window.api.escapeHtml(pipe.stage)}</span>
      `;
      pill.className = 'badge badge-accent font-mono';
    } else {
      pill.innerHTML = `
        <span class="status-indicator status-indicator-idle" style="background: var(--success);"></span>
        <span style="font-size: 12px; font-weight: 500;">All Systems Operational</span>
      `;
      pill.className = 'status-pill';
    }
  }

  bindGlobalEvents() {
    // Sidebar Navigation
    document.querySelectorAll('.sidebar-link').forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        const viewName = link.getAttribute('data-view');
        if (viewName) {
          window.state.setView(viewName);
        }
      });
    });

    // Global Omnibar Search
    const omnibar = document.getElementById('globalSearchInput');
    if (omnibar) {
      omnibar.addEventListener('input', (e) => {
        window.state.searchQuery = e.target.value;
        if (window.state.currentView !== 'leads' && window.state.currentView !== 'discover') {
          window.state.setView('leads');
        } else {
          // Re-render
          this.views[window.state.currentView].render(this.viewContainer);
        }
      });

      omnibar.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          window.state.searchQuery = omnibar.value;
          window.state.setView('discover');
        }
      });
    }

    // Keyboard Shortcuts: Cmd+K / Ctrl+K to search, Esc to close modal
    document.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        if (omnibar) {
          omnibar.focus();
          omnibar.select();
        }
      }
      if (e.key === 'Escape') {
        if (window.leadDetail) {
          window.leadDetail.close();
        }
      }
    });

    // Sidebar Collapse Toggle
    const btnToggleSidebar = document.getElementById('btnToggleSidebar');
    const sidebar = document.getElementById('appSidebar');
    if (btnToggleSidebar && sidebar) {
      btnToggleSidebar.addEventListener('click', () => {
        sidebar.classList.toggle('collapsed');
      });
    }
  }
}

// Bootstrap on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  window.app = new FlowizApp();
  window.app.init();
});
