/**
 * Flowiz Intelligence Platform — OSINT Provider Registry View
 * Redesigned with Light Pastel Futuristic Theme (flowiz.biz)
 */

class OsintView {
  constructor() {
    this.container = null;
  }

  render(container) {
    this.container = container;

    // The 10 official OSINT providers from Milestone 4 ProviderRegistry
    const providers = [
      {
        id: 'domain_intel',
        name: 'Domain Intelligence Provider',
        category: 'Network & Infrastructure',
        status: 'Active',
        badge: 'badge-success',
        icon: 'fa-network-wired',
        desc: 'Resolves canonical hostname, identifies primary hosting IP, checks SSL certificates, and traces DNS nameservers.',
        capabilities: ['DNS Resolution', 'SSL Verification', 'Nameserver Mapping'],
        cost: 'Free / Internal',
        priority: 1
      },
      {
        id: 'whois',
        name: 'WHOIS Registration Provider',
        category: 'Registrar & Ownership',
        status: 'Active',
        badge: 'badge-success',
        icon: 'fa-id-badge',
        desc: 'Queries domain registrar databases to extract entity registration timestamp, expiration date, and country of origin.',
        capabilities: ['Registrar Lookup', 'Creation Date', 'Country Tagging'],
        cost: 'Free / Public',
        priority: 2
      },
      {
        id: 'dns_mx',
        name: 'DNS / MX Records Provider',
        category: 'Mail Infrastructure',
        status: 'Active',
        badge: 'badge-success',
        icon: 'fa-server',
        desc: 'Extracts authoritative Mail Exchanger (MX) records to verify corporate email infrastructure legitimacy.',
        capabilities: ['MX Record Lookup', 'Mail Server Verification', 'Deliverability Prep'],
        cost: 'Free / Internal',
        priority: 3
      },
      {
        id: 'email_verifier',
        name: 'Email Verification Engine',
        category: 'Contact Verification',
        status: 'Active',
        badge: 'badge-success',
        icon: 'fa-envelope-circle-check',
        desc: 'Performs multi-step email syntax checks, domain MX validation, disposable domain checks, and SMTP handshake testing.',
        capabilities: ['Syntax Check', 'Disposable Domain Filter', 'MX Route Verification'],
        cost: 'Free / Internal',
        priority: 4
      },
      {
        id: 'opencorporates',
        name: 'OpenCorporates Registry',
        category: 'Legal Entity Registry',
        status: 'Active',
        badge: 'badge-success',
        icon: 'fa-building-columns',
        desc: 'Queries world’s largest open database of registered legal entities and corporate officers.',
        capabilities: ['Jurisdiction Match', 'Company Number Lookup', 'Filing Status'],
        cost: 'Public API',
        priority: 5
      },
      {
        id: 'zauba',
        name: 'Zauba Corp / MCA India',
        category: 'Indian Corporate Registry',
        status: 'Active',
        badge: 'badge-success',
        icon: 'fa-landmark',
        desc: 'Extracts Indian Ministry of Corporate Affairs (MCA) records, CIN identification, registered address, and director lists.',
        capabilities: ['CIN Lookup', 'Director Identification', 'Paid-up Capital'],
        cost: 'Public Web / Scraper',
        priority: 6
      },
      {
        id: 'social_discovery',
        name: 'Social Media Footprint Discovery',
        category: 'External Intelligence',
        status: 'Active',
        badge: 'badge-success',
        icon: 'fa-share-nodes',
        desc: 'Identifies verified corporate profiles across LinkedIn, Twitter/X, GitHub, Facebook, and Instagram.',
        capabilities: ['LinkedIn Company', 'Twitter Handle', 'GitHub Org', 'Social Reach'],
        cost: 'Free / OSINT',
        priority: 7
      },
      {
        id: 'phone_validation',
        name: 'Phone Validator & Telephony',
        category: 'Contact Validation',
        status: 'Active',
        badge: 'badge-success',
        icon: 'fa-phone-volume',
        desc: 'Validates international phone numbers using Google libphonenumber, standardizing to E.164 and detecting carrier country.',
        capabilities: ['E.164 Formatting', 'Country Detection', 'Format Validation'],
        cost: 'Free / Internal',
        priority: 8
      },
      {
        id: 'deep_contacts',
        name: 'Deep Contact Heuristic Scraper',
        category: 'Page Heuristics',
        status: 'Active',
        badge: 'badge-success',
        icon: 'fa-magnifying-glass-arrow-right',
        desc: 'Crawls dedicated contact, about, and team pages to extract obfuscated mailto links, phone lines, and executive bios.',
        capabilities: ['Regex Extraction', 'DOM Parsing', 'Executive Matching'],
        cost: 'Internal Crawler',
        priority: 9
      },
      {
        id: 'hunter',
        name: 'Hunter.io Domain Search & Verify',
        category: 'Commercial Data Provider',
        status: 'Deferred',
        badge: 'badge-warning',
        icon: 'fa-crosshairs',
        desc: 'Commercial email search and verification API. Intentionally deferred via configuration (HUNTER_ENABLED=false) to avoid unbudgeted quota consumption.',
        capabilities: ['Domain Search', 'Email Finder', 'Confidence Scoring'],
        cost: 'Commercial / Paid Quota',
        priority: 10
      }
    ];

    this.container.innerHTML = `
      <div class="view-header">
        <div>
          <div style="display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: var(--radius-pill); background: var(--flowiz-purple-badge-bg); border: 1px solid var(--flowiz-purple-badge-border); color: var(--flowiz-primary-purple-dark); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px;">
            <i class="fa-solid fa-satellite"></i> Modular OSINT Architecture
          </div>
          <h1 class="view-title">OSINT Provider Registry</h1>
          <div class="view-subtitle">
            Central ProviderRegistry orchestrating modular intelligence enrichment without data fragmentation.
          </div>
        </div>
        <div style="display: flex; gap: 10px;">
          <span class="badge badge-success font-mono">9 ACTIVE</span>
          <span class="badge badge-warning font-mono">1 DEFERRED (HUNTER)</span>
        </div>
      </div>

      <!-- Hunter Deferred Notice Banner -->
      <div class="card" style="margin-bottom: 28px; border-left: 4px solid var(--flowiz-warning); background: var(--flowiz-warning-bg); border-radius: var(--radius-lg);">
        <div style="display: flex; align-items: flex-start; gap: 14px;">
          <i class="fa-solid fa-triangle-exclamation text-warning" style="font-size: 20px; margin-top: 2px;"></i>
          <div>
            <div style="font-weight: 800; font-size: 14.5px; color: var(--flowiz-warning-text); margin-bottom: 4px;">
              Commercial Quota Protection Active: Hunter.io is Deferred
            </div>
            <div style="font-size: 13px; line-height: 1.5; color: var(--flowiz-warning-text);">
              As established in Milestone 4 & 6 architecture, <code class="font-mono" style="font-weight: 700;">HUNTER_ENABLED=false</code> is intentionally configured to preserve API budgets. Ingestion pipelines execute all 9 autonomous open-source OSINT providers without reliance on external paid credits.
            </div>
          </div>
        </div>
      </div>

      <!-- Providers Cards Grid -->
      <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 20px;">
        ${providers.map(p => this._renderProviderCard(p)).join('')}
      </div>
    `;
  }

  _renderProviderCard(p) {
    return `
      <div class="card" style="display: flex; flex-direction: column; justify-content: space-between; border-radius: var(--radius-lg); ${p.status === 'Deferred' ? 'border-style: dashed; background: #FFFDF8;' : ''}">
        <div>
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px;">
            <div style="display: flex; align-items: center; gap: 12px;">
              <div style="width: 42px; height: 42px; border-radius: var(--radius-md); background: ${p.status === 'Deferred' ? 'var(--flowiz-warning-bg)' : 'var(--flowiz-purple-badge-bg)'}; border: 1px solid ${p.status === 'Deferred' ? 'var(--flowiz-warning-border)' : 'var(--flowiz-purple-badge-border)'}; display: flex; align-items: center; justify-content: center; font-size: 18px; color: ${p.status === 'Deferred' ? 'var(--flowiz-warning)' : 'var(--flowiz-primary-purple)'};">
                <i class="fa-solid ${p.icon}"></i>
              </div>
              <div>
                <div style="font-weight: 800; font-size: 15px; color: var(--flowiz-text-primary);">${p.name}</div>
                <div class="text-caption text-muted">${p.category}</div>
              </div>
            </div>
            <span class="badge ${p.badge} font-mono">${p.status}</span>
          </div>

          <p class="text-secondary" style="font-size: 13px; line-height: 1.5; margin-bottom: 16px; min-height: 52px;">
            ${p.desc}
          </p>

          <div style="margin-bottom: 16px;">
            <div class="text-caption text-muted" style="margin-bottom: 8px; font-weight: 700;">CAPABILITIES:</div>
            <div style="display: flex; flex-wrap: wrap; gap: 6px;">
              ${p.capabilities.map(c => `
                <span class="badge badge-accent font-mono" style="font-size: 10.5px;">${c}</span>
              `).join('')}
            </div>
          </div>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center; padding-top: 14px; border-top: 1px solid var(--flowiz-border-subtle); font-size: 12.5px;">
          <div>
            <span class="text-muted">Type: </span>
            <span class="font-mono text-secondary" style="font-weight: 600;">${p.cost}</span>
          </div>
          <div>
            <span class="text-muted">Priority: </span>
            <span class="font-mono text-accent" style="font-weight: 700;">#${p.priority}</span>
          </div>
        </div>
      </div>
    `;
  }
}

window.OsintView = OsintView;
