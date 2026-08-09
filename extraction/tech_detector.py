from __future__ import annotations
import re
from typing import Any
from bs4 import BeautifulSoup

_HTML_RULES = [
    ('React', ['react.js', 'react.min.js', 'react-dom', '_next/', 'data-reactroot', '__reactFiber']),
    ('Next.js', ['_next/static', '_next/chunks', '__NEXT_DATA__']),
    ('Vue.js', ['vue.js', 'vue.min.js', 'vue@', '/vue/', 'data-v-']),
    ('Nuxt.js', ['_nuxt/', '__nuxt', 'nuxt.config']),
    ('Angular', ['angular.js', 'angular.min.js', 'ng-version', 'ng-app']),
    ('Svelte', ['svelte', '__svelte']),
    ('Gatsby', ['gatsby-', '___gatsby']),
    ('Remix', ['remix-', '__remixContext']),
    ('WordPress', ['wp-content/', 'wp-includes/', 'wordpress']),
    ('Shopify', ['cdn.shopify.com', 'shopify.com/s/', 'Shopify.theme']),
    ('Wix', ['wix.com', 'wixsite.com', 'wixstatic.com']),
    ('Webflow', ['webflow.com', 'webflow.css']),
    ('Squarespace', ['squarespace.com', 'squarespace-cdn']),
    ('Ghost', ['ghost.io', 'ghost.org', 'content/themes/ghost']),
    ('Drupal', ['drupal.js', 'drupal.org', '/sites/default/files']),
    ('Joomla', ['joomla', '/media/com_']),
    ('Google Analytics', ['google-analytics.com', 'gtag/js', 'ga.js', '_ga']),
    ('Google Tag Manager', ['googletagmanager.com/gtm.js', 'GTM-']),
    ('HubSpot', ['js.hs-scripts.com', 'hubspot.com', 'hs-analytics']),
    ('Segment', ['cdn.segment.com', 'analytics.js', 'segment.io']),
    ('Intercom', ['intercom.io', 'intercomcdn.com', 'Intercom(']),
    ('Hotjar', ['hotjar.com', 'hjid', 'hjsv']),
    ('Mixpanel', ['cdn.mxpnl.com', 'mixpanel.com', 'mixpanel.track']),
    ('Crisp', ['crisp.chat', 'client.crisp.chat']),
    ('Zendesk', ['zendesk.com', 'zopim.com', 'zESettings']),
    ('Drift', ['drift.com', 'js.driftt.com']),
    ('Cloudflare', ['cloudflare.com', '__cf_bm', 'cf-ray', 'cdn-cgi']),
    ('Fastly', ['fastly.net', 'fastly-restarts']),
    ('AWS CloudFront', ['cloudfront.net']),
    ('Vercel', ['vercel.app', '_vercel', 'x-vercel']),
    ('Netlify', ['netlify.com', 'netlify.app', 'nf_jwt']),
    ('Stripe', ['js.stripe.com', 'stripe.js', 'stripe-js']),
    ('PayPal', ['paypal.com/sdk', 'paypalobjects.com']),
    ('Chargebee', ['chargebee.com', 'js.chargebee.com']),
    ('Salesforce', ['salesforce.com', 'force.com', 'sfdccdn']),
    ('Pardot', ['go.pardot.com', 'pardot.com']),
    ('ActiveCampaign', ['trackcmp.net', 'activecampaign.com']),
    ('WooCommerce', ['woocommerce', 'wc-ajax']),
    ('Magento', ['mage/', 'magento', 'varien']),
    ('Bootstrap', ['bootstrap.min.css', 'bootstrap.css', 'bootstrap.bundle']),
    ('jQuery', ['jquery.min.js', 'jquery.js', 'jquery-']),
    ('Tailwind CSS', ['tailwind.css', 'tailwindcss']),
    ('Font Awesome', ['font-awesome', 'fontawesome']),
    ('Cloudinary', ['cloudinary.com', 'res.cloudinary']),
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
