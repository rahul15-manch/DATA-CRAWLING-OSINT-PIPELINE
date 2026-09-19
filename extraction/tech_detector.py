from __future__ import annotations
import re
from typing import Any
from bs4 import BeautifulSoup

_HTML_RULES = [
    # ── Frontend Frameworks ───────────────────────────────────────────────
    ('React',      ['react.js', 'react.min.js', 'react-dom', '_next/', 'data-reactroot', '__reactFiber']),
    ('Next.js',    ['_next/static', '_next/chunks', '__NEXT_DATA__']),
    ('Vue.js',     ['vue.js', 'vue.min.js', 'vue@', '/vue/', 'data-v-']),
    ('Nuxt.js',    ['_nuxt/', '__nuxt', 'nuxt.config']),
    ('Angular',    ['angular.js', 'angular.min.js', 'ng-version', 'ng-app']),
    ('Svelte',     ['svelte', '__svelte']),
    ('Gatsby',     ['gatsby-', '___gatsby']),
    ('Remix',      ['remix-', '__remixContext']),
    ('Astro',      ['astro-island', 'data-astro-', '@astrojs']),
    ('Vite',       ['/@vite/', 'vite.config', '__vitePreload']),
    ('Alpine.js',  ['x-data=', 'x-init=', 'alpine.js', 'alpinejs']),
    ('Ember',      ['ember.js', 'ember-view', 'ember-application']),
    ('Backbone.js',['backbone.js', 'backbone.min.js']),

    # ── CMS & Website Builders ────────────────────────────────────────────
    ('WordPress',    ['wp-content/', 'wp-includes/', 'wordpress']),
    ('Shopify',      ['cdn.shopify.com', 'shopify.com/s/', 'Shopify.theme']),
    ('Wix',          ['wix.com', 'wixsite.com', 'wixstatic.com']),
    ('Webflow',      ['webflow.com', 'webflow.css']),
    ('Squarespace',  ['squarespace.com', 'squarespace-cdn']),
    ('Ghost',        ['ghost.io', 'ghost.org', 'content/themes/ghost']),
    ('Drupal',       ['drupal.js', 'drupal.org', '/sites/default/files']),
    ('Joomla',       ['joomla', '/media/com_']),

    # ── Analytics & Tag Management ────────────────────────────────────────
    ('Google Analytics',   ['google-analytics.com', 'gtag/js', 'ga.js', '_ga']),
    ('Google Tag Manager', ['googletagmanager.com/gtm.js', 'GTM-']),
    ('Segment',            ['cdn.segment.com', 'analytics.js', 'segment.io']),
    ('Mixpanel',           ['cdn.mxpnl.com', 'mixpanel.com', 'mixpanel.track']),
    ('PostHog',            ['posthog.com', 'posthog-js', 'posthog.capture']),
    ('Amplitude',          ['amplitude.com', 'amplitude-js']),
    ('Hotjar',             ['hotjar.com', 'hjid', 'hjsv']),
    ('FullStory',          ['fullstory.com', 'fs.js', 'window.FS']),
    ('Heap',               ['heapanalytics.com', 'heap.io']),
    ('LaunchDarkly',       ['launchdarkly.com', 'ldclient']),

    # ── CRM & Support Tools ───────────────────────────────────────────────
    ('HubSpot',        ['js.hs-scripts.com', 'hubspot.com', 'hs-analytics']),
    ('Intercom',       ['intercom.io', 'intercomcdn.com', 'Intercom(']),
    ('Zendesk',        ['zendesk.com', 'zopim.com', 'zESettings']),
    ('Drift',          ['drift.com', 'js.driftt.com']),
    ('Crisp',          ['crisp.chat', 'client.crisp.chat']),
    ('Salesforce',     ['salesforce.com', 'force.com', 'sfdccdn']),
    ('Pardot',         ['go.pardot.com', 'pardot.com']),
    ('ActiveCampaign', ['trackcmp.net', 'activecampaign.com']),
    ('Marketo',        ['munchkin.marketo.net', 'marketo.com']),
    ('Klaviyo',        ['klaviyo.com', 'kl_']),

    # ── Payment & E-commerce ──────────────────────────────────────────────
    ('Stripe',      ['js.stripe.com', 'stripe.js', 'stripe-js']),
    ('PayPal',      ['paypal.com/sdk', 'paypalobjects.com']),
    ('Chargebee',   ['chargebee.com', 'js.chargebee.com']),
    ('WooCommerce', ['woocommerce', 'wc-ajax']),
    ('Magento',     ['mage/', 'magento', 'varien']),

    # ── Cloud & Infrastructure ────────────────────────────────────────────
    ('Cloudflare',    ['cloudflare.com', '__cf_bm', 'cf-ray', 'cdn-cgi']),
    ('Fastly',        ['fastly.net', 'fastly-restarts']),
    ('AWS CloudFront',['cloudfront.net']),
    ('AWS S3',        ['s3.amazonaws.com', 's3-website', 'aws.amazon.com/s3']),
    ('Firebase',      ['firebaseapp.com', 'firebase.google.com', 'firebaseio.com']),
    ('Supabase',      ['supabase.co', 'supabase.io', 'supabase-js']),
    ('Vercel',        ['vercel.app', '_vercel', 'x-vercel']),
    ('Netlify',       ['netlify.com', 'netlify.app', 'nf_jwt']),

    # ── Styling & UI ──────────────────────────────────────────────────────
    ('Bootstrap',     ['bootstrap.min.css', 'bootstrap.css', 'bootstrap.bundle']),
    ('Tailwind CSS',  ['tailwind.css', 'tailwindcss', 'class="flex ', 'class="grid ']),
    ('Material UI',   ['material-ui', '@mui/', 'MuiButtonBase']),
    ('Ant Design',    ['antd.css', 'antd.min.css', 'ant-design']),
    ('Font Awesome',  ['font-awesome', 'fontawesome']),
    ('Cloudinary',    ['cloudinary.com', 'res.cloudinary']),

    # ── Build Tools & Runtime ─────────────────────────────────────────────
    ('jQuery',        ['jquery.min.js', 'jquery.js', 'jquery-']),
    ('Webpack',       ['webpack-', 'webpackJsonp', '__webpack_require__']),
    ('Babel',         ['babel.min.js', 'regeneratorRuntime']),
]

_HEADER_RULES = [
    ('Nginx', ['nginx']),
    ('Apache', ['apache']),
    ('Cloudflare', ['cloudflare']),
    ('Vercel', ['vercel']),
    ('Netlify', ['netlify']),
    ('AWS', ['amazonaws.com', 'aws']),
    ('PHP', ['php/']),
    ('ASP.NET', ['asp.net', 'x-aspnet']),
    ('Node.js', ['node.js', 'express']),
    ('Next.js', ['next.js']),
    ('Python', ['python/', 'gunicorn', 'uvicorn', 'django', 'flask', 'fastapi']),
    ('Ruby on Rails', ['phusion passenger', 'thin', 'puma', 'rails']),
    ('Java', ['jetty/', 'tomcat', 'jboss']),
]

_META_GENERATOR_MAP = {
    'wordpress': 'WordPress', 'joomla': 'Joomla', 'drupal': 'Drupal',
    'squarespace': 'Squarespace', 'wix': 'Wix', 'ghost': 'Ghost',
    'shopify': 'Shopify', 'webflow': 'Webflow',
}

def detect_tech_stack(html: str, headers: dict[str, Any]) -> list[str]:
    detected: set[str] = set()
    html_lower = (html or '').lower()
    for tech_name, patterns in _HTML_RULES:
        for pattern in patterns:
            if pattern.lower() in html_lower:
                detected.add(tech_name)
                break
    if headers:
        header_blob = ' '.join(str(v).lower() for v in headers.values())
        for tech_name, patterns in _HEADER_RULES:
            for pattern in patterns:
                if pattern.lower() in header_blob:
                    detected.add(tech_name)
                    break
    try:
        soup = BeautifulSoup(html or '', 'html.parser')
        for meta in soup.find_all('meta', attrs={'name': 'generator'}):
            content = (meta.get('content') or '').lower()
            for keyword, tech in _META_GENERATOR_MAP.items():
                if keyword in content:
                    detected.add(tech)
    except Exception:
        pass
    return sorted(detected)
