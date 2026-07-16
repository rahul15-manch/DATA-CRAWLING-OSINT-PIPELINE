import logging
import time
from typing import Optional
from .provider_stats import provider_stats
from .proxy_stats import proxy_stats
from .pipeline_stats import pipeline_stats
import utils.stats_tracker as stats

logger = logging.getLogger(__name__)

def render_dashboard(execution_time_s: float, keyword: str) -> None:
    """Renders a beautifully formatted execution report on standard output."""
    # Read search manager cache metrics
    from search.manager import get_search_manager
    sm = get_search_manager()
    cache_stats = sm.cache.get_stats()
    cache_hits = sm.cache_hits
    cache_misses = sm.cache_misses
    total_queries = sm.total_queries

    # Sync duplicates merged count from search manager for complete output consistency
    pipeline_stats.duplicates_merged = sm.total_duplicates_removed

    print()
    print("=" * 60)
    print("            FLOWIZ SEARCH & ETL PIPELINE DASHBOARD            ")
    print("=" * 60)
    avg_lead_cost = execution_time_s / max(1, pipeline_stats.unique_master_records)
    
    print(f"  Target Keyword   : {keyword!r}")
    print(f"  Execution Time   : {execution_time_s:.2f}s")
    print(f"  Avg Lead Cost    : {avg_lead_cost:.2f}s/lead")
    print("-" * 60)

    # 1. High-Level Summary
    print(f"  Total Queries    : {total_queries:<12} | Cache Hits          : {cache_hits} ({cache_hits / max(1, total_queries):.0%})")
    print(f"  Successful Hits  : {cache_stats.get('successful_hits', 0):<12} | Zero-result Hits    : {cache_stats.get('zero_result_hits', 0)}")
    print(f"  Expired Entries  : {cache_stats.get('expired_entries', 0):<12} | Cache Bypasses      : {cache_stats.get('bypasses', 0)}")
    print(f"  Debug Bypasses   : {cache_stats.get('debug_bypasses', 0):<12} | Live Executions     : {sm.queries_live_run}")
    print(f"  Leads Discovered : {pipeline_stats.unique_master_records:<12} | Duplicates Merged : {pipeline_stats.duplicates_merged}")
    print(f"  Dropped (Valid)  : {pipeline_stats.dropped_validation:<12} | Dropped (Domain)  : {pipeline_stats.dropped_no_domain}")
    print("-" * 60)

    # 2. Provider Breakdown
    print("PROVIDER PERFORMANCE:")
    report = provider_stats.compile_report()
    if not report:
        print("  No search queries were executed in this run.")
    else:
        ranked = []
        for prov_name, r in report.items():
            queries = r["queries"]
            score = r.get("score", 0.0)
            http_succ = r.get("http_successes", 0)
            parser_succ = r.get("parser_successes", 0)
            zero_results = r.get("zero_results", 0)
            organic = r.get("organic_results", 0)
            accepted = r.get("accepted_companies", 0)
            
            ranked.append((score, prov_name, r))
            if queries == 0:
                print(f"  - {prov_name:<16}: Skipped (served from cache)")
            else:
                print(
                    f"  - {prov_name:<16}: Score={score:.2f} | HTTP={http_succ}/{queries} | Parser={parser_succ} | Zero={zero_results} | Org={organic} | Acc={accepted}"
                )
                print(
                    f"                    Latencies: Avg={r['avg_latency']:.2f}s, Med={r['median_latency']:.2f}s, p95={r['p95_latency']:.2f}s "
                    f"| Rates: 429={r['rate_429']:.0%}, CAP={r['captcha_rate']:.0%}, Timeout={r['timeout_rate']:.0%}"
                )
        ranked.sort(key=lambda item: item[0], reverse=True)
        print("  Top Providers   : " + ", ".join(name for _, name, _ in ranked[:3]))
        print("  Worst Providers : " + ", ".join(name for _, name, _ in ranked[-3:]))
    print("-" * 60)

    # 3. Proxy Performance Analysis
    print("PROXY PERFORMANCE:")
    best_proxy = "N/A"
    best_latency = float("inf")
    worst_proxy = "N/A"
    worst_failure_rate = -1.0

    for proxy_url, metrics in proxy_stats.stats.items():
        reqs = metrics["requests"]
        succ = metrics["successes"]
        fails = metrics["failures"]
        fail_rate = fails / max(1, reqs)
        
        avg_lat = (sum(metrics["latencies_ms"]) / max(1, len(metrics["latencies_ms"]))) if metrics["latencies_ms"] else float("inf")
        
        if succ > 0 and avg_lat < best_latency:
            best_latency = avg_lat
            best_proxy = proxy_url
            
        if fail_rate > worst_failure_rate:
            worst_failure_rate = fail_rate
            worst_proxy = proxy_url

    best_lat_str = f"{best_latency / 1000.0:.2f}s" if best_latency != float("inf") else "N/A"
    print(f"  Best Proxy       : {best_proxy} (Avg Latency: {best_lat_str})")
    print(f"  Worst Proxy      : {worst_proxy} (Failure Rate: {worst_failure_rate:.0%})")
    if proxy_stats.stats:
        busiest_proxy, busiest = max(proxy_stats.stats.items(), key=lambda item: item[1]["requests"])
        print(f"  Busiest Proxy    : {busiest_proxy} ({busiest['requests']} requests)")
    print("-" * 60)

    # 4. Discovery Funnel
    funnel = stats.get()
    logical_queries = funnel.get('funnel_requests_sent', 0)
    
    # Authoritative single-sources for network/parser metrics
    physical_reqs = sum(p.get("request_count", 0) for p in provider_stats.stats.values())
    http_succ = sum(p["http_successes"] for p in provider_stats.stats.values())
    parser_succ = sum(p["parser_successes"] for p in provider_stats.stats.values())
    
    biz_cands = funnel.get('funnel_business_candidates', 0)
    biz_acc = funnel.get('funnel_business_accepted', 0)
    home_crawled = funnel.get('funnel_homepage_crawled', 0)
    cont_ext = funnel.get('funnel_contacts_extracted', 0)
    leads_exp = funnel.get('funnel_leads_exported', 0)
    cache_served_queries = funnel.get("cache_served_queries", 0)

    print("TELEMETRY FUNNEL:")
    print(f"  1. Logical Queries     : {logical_queries}")
    print(f"  2. Physical Requests   : {physical_reqs}")
    print(f"  3. HTTP Success        : {http_succ}")
    print(f"  4. Parser Success      : {parser_succ}")
    print(f"  5. Business Candidates : {biz_cands}")
    print(f"  6. Business Accepted   : {biz_acc}")
    print(f"  7. Homepage Crawled    : {home_crawled}")
    print(f"  8. Contacts Extracted  : {cont_ext}")
    print(f"  9. Leads Exported      : {leads_exp}")
    print(f"     Cache Served Queries: {cache_served_queries}")
    print("-" * 60)

    # 5. Source Attribution
    if pipeline_stats.source_breakdown:
        print("TOP SOURCES DISCOVERED:")
        sorted_sources = sorted(pipeline_stats.source_breakdown.items(), key=lambda x: x[1], reverse=True)[:5]
        for src, cnt in sorted_sources:
            print(f"  - {src:<20}: {cnt} leads")
    else:
        print("  No company sources were identified.")

    try:
        from query.expansion import get_query_feedback_snapshot

        feedback = get_query_feedback_snapshot()
        if feedback:
            print("QUERY TEMPLATE FEEDBACK:")
            ranked_feedback = []
            for query, counts in feedback.items():
                if not query.startswith("template:"):
                    continue
                runs = counts.get("queries_run", 0)
                leads = counts.get("leads_found", 0)
                roi = (leads / runs) if runs > 0 else 0.0
                ranked_feedback.append((roi, query.replace("template:", ""), runs, leads))
                
            ranked_feedback.sort(key=lambda item: item[0], reverse=True)
            for roi, query, runs, leads in ranked_feedback[:10]:
                print(f"  - {query:<40} Runs: {runs:<4} Leads: {leads:<4} ROI: {roi:.0%}")
    except Exception:
        pass
    print("=" * 60)
    print()
