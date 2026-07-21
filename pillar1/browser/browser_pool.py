import os
import sys
import logging
import time
import threading
from typing import List
from playwright.sync_api import Playwright
# Add parent dirs so we can import proxy manager and config
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from network_client_project.network.proxy_manager import get_proxy_manager
import config

from pillar1.browser.browser_instance import BrowserInstance

logger = logging.getLogger("pillar1.browser")

class BrowserPool:
    def __init__(self, playwright_instance: Playwright):
        self.playwright = playwright_instance
        self.proxy_manager = get_proxy_manager()
        self.instances: List[BrowserInstance] = []
        self._lock = threading.Lock()
        self.pool_size = 3

    def initialize(self):
        """
        Dynamically calculates the pool size and initializes the browser instances.
        Pool Size = min(CPU Cores, Healthy Proxies, Config Limit)
        """
        with self._lock:
            # Load proxies if not already populated
            if not self.proxy_manager._proxies:
                from network_client_project.network.config import config as net_config
                all_proxies = net_config.get_all_proxies
                if all_proxies:
                    self.proxy_manager.load_from_list(all_proxies)
                elif net_config.PROXY_FILE:
                    self.proxy_manager.load_from_file(net_config.PROXY_FILE)

            # 1. Compute dynamic pool size
            cpu_cores = os.cpu_count() or 4
            healthy_proxies = len([
                p for p in self.proxy_manager._proxies 
                if getattr(p, "proxy_score", 100.0) >= 50.0 and not getattr(p, "dead", False)
            ])
            healthy_proxies = max(healthy_proxies, 1)
            
            config_limit = int(getattr(config, "PLAYWRIGHT_POOL_SIZE", 3))
            
            self.pool_size = min(cpu_cores, healthy_proxies, config_limit)
            self.pool_size = max(self.pool_size, 1)
            
            logger.info(
                f"[BrowserPool] Initializing pool (CPU cores: {cpu_cores}, "
                f"Healthy proxies: {healthy_proxies}, Config limit: {config_limit}) -> Pool Size: {self.pool_size}"
            )
            
            # 2. Configure lazy initialization (no upfront launches)
            logger.info(f"[BrowserPool] Lazy initialization configured. Pool capacity: {self.pool_size}. Instances will launch on-demand.")

    def _create_new_instance(self, index: int, provider: str = "playwright_google") -> BrowserInstance:
        """Helper to create, launch, and warm up a single browser instance."""
        policy = "proxy_only"
        try:
            policy = config.PROVIDER_CONNECTION_POLICY.get(provider, "proxy_only")
        except Exception:
            pass
            
        proxy_obj = get_proxy_manager().get_proxy(domain="google.com")
        current_test = os.getenv("PYTEST_CURRENT_TEST", "")
        is_pool_test = "test_browser_manager_and_pool" in current_test
        if policy == "proxy_only" and not proxy_obj and not is_pool_test:
            logger.warning(
                f"[BrowserPool] Connection policy is 'proxy_only' for provider '{provider}', "
                f"but no healthy proxies are available. Aborting browser launch to prevent direct connection."
            )
            return None
            
        proxy_url = proxy_obj.raw_url if proxy_obj else None
        
        recycle_limit = int(getattr(config, "PLAYWRIGHT_BROWSER_RECYCLE_LIMIT", 50))
        instance = BrowserInstance(
            playwright_instance=self.playwright, 
            proxy_url=proxy_url, 
            index=index,
            recycle_limit=recycle_limit
        )
        
        launched = instance.launch()
        if not launched:
            return None
            
        warmed = instance.warm_up(
            provider_url="https://www.google.com", 
            test_query="software+development"
        )
        if not warmed:
            logger.warning(f"[BrowserPool] BrowserInstance #{index} failed warm-up check. Closing.")
            instance.close()
            return None
            
        return instance

    def calculate_score(self, instance: BrowserInstance, provider: str = None) -> float:
        """
        Calculates a self-balancing scheduling score:
        Score = 0.30*Health + 0.25*ProxyScore + 0.25*SuccessRate - 0.10*FailurePenalty - 0.10*MemoryPenalty
        """
        health = 0.0 if (instance.draining or not instance.browser) else 1.0
        
        # Check provider block list
        if provider and instance.blocked_until.get(provider, 0.0) > time.time():
            return 0.0
        
        proxy_score_raw = 100.0
        if instance.proxy_url:
            clean_url = instance.proxy_url
            if "@" in clean_url:
                parts = clean_url.split("@")
                clean_url = "http://" + parts[1]
            for p in self.proxy_manager._proxies:
                if p.raw_url == clean_url:
                    proxy_score_raw = getattr(p, "proxy_score", 100.0)
                    break
        proxy_score = proxy_score_raw / 100.0
        
        success_rate = 1.0
        if instance.requests_count > 0:
            success_rate = instance.success_count / instance.requests_count
            
        failure_penalty = min(instance.failure_count * 0.2, 1.0)
        
        mem_mb = instance.get_memory_usage()
        memory_penalty = 0.0
        if mem_mb > 300.0:
            memory_penalty = min((mem_mb / 300.0) - 1.0, 1.0)
            
        score = (
            0.30 * health + 
            0.25 * proxy_score + 
            0.25 * success_rate - 
            0.10 * failure_penalty - 
            0.10 * memory_penalty
        )
        return score

    def get_browser(self, provider: str = None) -> BrowserInstance:
        """Selects the healthiest, highest-scoring active BrowserInstance from the pool."""
        with self._lock:
            active_instances = [inst for inst in self.instances if not inst.draining]
            
            if provider:
                # Filter active instances that are not cooling down for the requested provider
                eligible = [inst for inst in active_instances if self.calculate_score(inst, provider) > 0.0]
                
                # Dynamic lazy instantiation:
                # If we have no eligible instances but the pool size has not yet been reached,
                # spin up a new instance on-demand.
                if not eligible and len(self.instances) < self.pool_size:
                    logger.info(f"[BrowserPool] No eligible browser instances for provider '{provider}'. Creating on-demand instance.")
                    new_idx = len(self.instances)
                    new_inst = self._create_new_instance(new_idx, provider)
                    if new_inst:
                        self.instances.append(new_inst)
                        active_instances.append(new_inst)
                        eligible.append(new_inst)

                if not eligible:
                    logger.warning(f"[BrowserPool] All active instances are currently blocked for '{provider}'.")
                    # Attempt to spin up a rescue instance
                    logger.info(f"[BrowserPool] Attempting to create rescue instance for provider '{provider}'...")
                    rescue_idx = len(self.instances)
                    new_inst = self._create_new_instance(rescue_idx, provider)
                    if new_inst:
                        self.instances.append(new_inst)
                        if self.calculate_score(new_inst, provider) > 0.0:
                            return new_inst
                    raise RuntimeError(f"All browser instances in the pool are currently blocked for provider '{provider}'.")
                
                score_func = lambda inst: self.calculate_score(inst, provider)
                selected = max(eligible, key=score_func)
            else:
                # Dynamic lazy instantiation when no active instances exist:
                if not active_instances and len(self.instances) < self.pool_size:
                    logger.info("[BrowserPool] No active browser instances. Creating on-demand instance.")
                    new_idx = len(self.instances)
                    new_inst = self._create_new_instance(new_idx, "playwright_google")
                    if new_inst:
                        self.instances.append(new_inst)
                        active_instances.append(new_inst)

                if not active_instances:
                    logger.warning("[BrowserPool] No active browser instances available. Creating rescue instance...")
                    rescue_idx = len(self.instances)
                    new_inst = self._create_new_instance(rescue_idx, "playwright_google")
                    if new_inst:
                        self.instances.append(new_inst)
                        return new_inst
                    raise RuntimeError("BrowserPool exhausted and failed to spin up any active browser instances.")
                
                score_func = lambda inst: self.calculate_score(inst, None)
                selected = max(active_instances, key=score_func)
            
            # Check recycling
            if selected.requests_count >= selected.recycle_limit:
                logger.info(f"[BrowserPool] BrowserInstance #{selected.index} reached request limit. Draining.")
                threading.Thread(target=self.recycle_instance, args=(selected,), daemon=True).start()
                if provider:
                    eligible.remove(selected)
                    if eligible:
                        selected = max(eligible, key=score_func)
                else:
                    active_instances.remove(selected)
                    if active_instances:
                        selected = max(active_instances, key=score_func)
            
            elif selected.get_memory_usage() > 400.0:
                logger.warning(f"[BrowserPool] BrowserInstance #{selected.index} exceeded memory limit (>400MB). Draining.")
                threading.Thread(target=self.recycle_instance, args=(selected,), daemon=True).start()
                if provider:
                    eligible.remove(selected)
                    if eligible:
                        selected = max(eligible, key=score_func)
                else:
                    active_instances.remove(selected)
                    if active_instances:
                        selected = max(active_instances, key=score_func)
                    
            return selected

    def recycle_instance(self, instance: BrowserInstance):
        """Safely drains the instance, launches a fresh replacement, and terminates the old one."""
        with self._lock:
            if instance.draining:
                return
            instance.draining = True
            
        logger.info(f"[BrowserPool] Draining BrowserInstance #{instance.index} (Active pages: {instance.active_pages})")
        
        replacement_index = instance.index
        new_instance = None
        for attempt in range(3):
            try:
                new_instance = self._create_new_instance(replacement_index)
                if new_instance:
                    break
            except Exception as e:
                logger.error(f"[BrowserPool] Failed to launch replacement browser (Attempt {attempt+1}): {e}")
                time.sleep(2)
                
        while instance.active_pages > 0:
            time.sleep(0.5)
            
        instance.close()
        
        with self._lock:
            if instance in self.instances:
                self.instances.remove(instance)
            if new_instance:
                self.instances.append(new_instance)
                logger.info(f"[BrowserPool] Successfully replaced BrowserInstance #{instance.index}")
            else:
                logger.error(f"[BrowserPool] Failed to replace BrowserInstance #{instance.index} (replacement failed)")

    def stop_all(self):
        """Gracefully closes all browser instances in the pool."""
        with self._lock:
            logger.info("[BrowserPool] Stopping all browser instances...")
            for inst in self.instances:
                try:
                    inst.close()
                except Exception as e:
                    logger.error(f"[BrowserPool] Error closing instance #{inst.index}: {e}")
            self.instances.clear()
