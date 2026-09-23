/**
 * Flowiz Intelligence Platform — Centralized API Client & Data Access Layer
 * Connects directly to existing FastAPI backend contracts.
 */

class FlowizApiClient {
  constructor(baseUrl = '') {
    this.baseUrl = baseUrl;
    this._statusPollTimer = null;
  }

  /**
   * Safe HTML escaping helper to prevent XSS from un-sanitized scraped data.
   */
  escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /**
   * Generic request wrapper with timeout and error normalization.
   */
  async _request(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    const defaultHeaders = {
      'Accept': 'application/json',
    };

    const config = {
      ...options,
      headers: {
        ...defaultHeaders,
        ...options.headers,
      },
    };

    try {
      const response = await fetch(url, config);
      if (!response.ok) {
        let errDetail = `HTTP ${response.status} ${response.statusText}`;
        try {
          const errData = await response.json();
          if (errData && errData.detail) {
            errDetail = typeof errData.detail === 'string' ? errData.detail : JSON.stringify(errData.detail);
          } else if (errData && errData.error) {
            errDetail = errData.error;
          }
        } catch (_) {}
        throw new Error(errDetail);
      }
      return await response.json();
    } catch (err) {
      console.error(`[FlowizApiClient] Request failed for ${endpoint}:`, err);
      throw err;
    }
  }

  /**
   * Fetch live pipeline status telemetry.
   */
  async getStatus() {
    return await this._request('/api/status');
  }

  /**
   * Trigger background lead discovery pipeline.
   */
  async startSearch(keyword) {
    if (!keyword || keyword.trim().length < 2) {
      throw new Error('Search query must be at least 2 characters long.');
    }
    const cleanKw = encodeURIComponent(keyword.trim());
    return await this._request(`/api/search?keyword=${cleanKw}`, {
      method: 'POST',
    });
  }

  /**
   * Fetch category and industry counts.
   */
  async getCategories() {
    const res = await this._request('/api/categories');
    return (res && res.categories) ? res.categories : (res || {});
  }

  /**
   * Query filtered leads from canonical flowiz_leads with pagination.
   */
  async getLeads({ category, keyword, domain, industry, limit = 50, offset = 0 } = {}) {
    const params = new URLSearchParams();
    if (category) params.append('category', category);
    if (keyword) params.append('keyword', keyword);
    if (domain) params.append('domain', domain);
    if (industry) params.append('industry', industry);
    params.append('limit', String(limit));
    params.append('offset', String(offset));

    const qs = params.toString();
    const res = await this._request(`/api/leads${qs ? `?${qs}` : ''}`);
    return (res && Array.isArray(res.leads)) ? res.leads : (Array.isArray(res) ? res : []);
  }

  /**
   * Bulk dumps all verified leads from canonical storage flowiz_leads.
   */
  async getAllLeads() {
    const res = await this._request('/api/leads/all');
    if (res && Array.isArray(res.data)) {
      return res.data;
    }
    if (res && Array.isArray(res.leads)) {
      return res.leads;
    }
    return Array.isArray(res) ? res : [];
  }

  /**
   * Poll live status until completed or error.
   */
  pollStatus(onUpdate, onFinish, intervalMs = 1500) {
    if (this._statusPollTimer) {
      clearInterval(this._statusPollTimer);
    }

    const poll = async () => {
      try {
        const state = await this.getStatus();
        if (onUpdate) onUpdate(state);

        if (state.status === 'completed' || state.status === 'error') {
          clearInterval(this._statusPollTimer);
          this._statusPollTimer = null;
          if (onFinish) onFinish(state);
        }
      } catch (err) {
        console.error('[FlowizApiClient] Poll error:', err);
      }
    };

    poll();
    this._statusPollTimer = setInterval(poll, intervalMs);
  }

  /**
   * Stop polling.
   */
  stopPolling() {
    if (this._statusPollTimer) {
      clearInterval(this._statusPollTimer);
      this._statusPollTimer = null;
    }
  }

  /**
   * Client-side JSON file download helper.
   */
  exportJson(data, filename = 'flowiz_leads_export.json') {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  /**
   * Client-side CSV file download helper.
   */
  exportCsv(leads, filename = 'flowiz_leads_export.csv') {
    if (!leads || !leads.length) return;
    const headers = [
      'Company Name', 'Domain', 'Industry', 'Lead Score', 'Quality',
      'Location', 'Emails', 'Phones', 'Website', 'LinkedIn'
    ];

    const rows = leads.map(l => [
      `"${(l.company_name || '').replace(/"/g, '""')}"`,
      `"${(l.domain || '').replace(/"/g, '""')}"`,
      `"${(l.industry || l.company_type || '').replace(/"/g, '""')}"`,
      l.lead_score || 0,
      `"${(l.lead_quality || 'Low').replace(/"/g, '""')}"`,
      `"${(l.location || l.country || '').replace(/"/g, '""')}"`,
      `"${(Array.isArray(l.emails) ? l.emails.join('; ') : '').replace(/"/g, '""')}"`,
      `"${(Array.isArray(l.phones) ? l.phones.join('; ') : '').replace(/"/g, '""')}"`,
      `"${(l.website || '').replace(/"/g, '""')}"`,
      `"${(l.linkedin || '').replace(/"/g, '""')}"`
    ]);

    const csvContent = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }
}

// Global API instance
window.api = new FlowizApiClient();
