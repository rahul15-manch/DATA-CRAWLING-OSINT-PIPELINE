import logging
import logging.handlers
import os
from pathlib import Path
from typing import Optional

class NetworkLogger:
    """
    Configures a production-grade logging system for the network client.
    Supports file rotation, distinct log levels, and detailed network telemetry.
    """
    
    _initialized = False

    @classmethod
    def setup(cls, log_dir: str = "logs", level: int = logging.INFO):
        """
        Initializes the global logging configuration. Should only be called once.
        """
        if cls._initialized:
            return
            
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        
        # 1. Base format: Time | Level | Thread | Component | Message
        log_format = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(threadName)-10s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # 2. Console Handler (Standard Output)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_format)
        console_handler.setLevel(level)

        # 3. Rotating File Handler for General Logs (INFO and above)
        # Keeps 5 backup files, max 10MB each. Prevents logs from consuming the whole hard drive.
        info_file_handler = logging.handlers.RotatingFileHandler(
            filename=os.path.join(log_dir, 'network.log'),
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5
        )
        info_file_handler.setFormatter(log_format)
        info_file_handler.setLevel(logging.INFO)

        # 4. Rotating File Handler exclusively for ERRORS (WARNING and above)
        # Crucial for quickly diagnosing broken proxies or WAF blocks without sifting through info logs.
        error_file_handler = logging.handlers.RotatingFileHandler(
            filename=os.path.join(log_dir, 'errors.log'),
            maxBytes=10 * 1024 * 1024,
            backupCount=5
        )
        error_file_handler.setFormatter(log_format)
        error_file_handler.setLevel(logging.WARNING)

        # 5. Configure the root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG) # Catch everything, let handlers filter
        
        # Remove any existing handlers to prevent duplicate logs
        if root_logger.hasHandlers():
            root_logger.handlers.clear()
            
        root_logger.addHandler(console_handler)
        root_logger.addHandler(info_file_handler)
        root_logger.addHandler(error_file_handler)
        
        # Silence noisy third-party libraries
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("fake_useragent").setLevel(logging.ERROR)

        cls._initialized = True
        logging.getLogger(__name__).info("Network Logging System Initialized.")

    @staticmethod
    def log_request(
        logger_instance: logging.Logger, 
        method: str, 
        url: str, 
        status_code: int, 
        latency_ms: float, 
        proxy_url: Optional[str] = None,
        retries: int = 0,
        user_agent: Optional[str] = None,
        proxy_rotated: bool = False,
        proxy_failed: bool = False,
        cooldown: float = 0.0
    ):
        """
        A standardized way to log network telemetry data.
        """
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        
        p_mask = "No Proxy"
        if proxy_url:
            # Mask the proxy credentials in logs for security!
            if "@" in proxy_url:
                parts = proxy_url.split("@")
                p_mask = f"***@{parts[1]}"
            else:
                p_mask = proxy_url

        ua_mask = user_agent[:30] + "..." if user_agent and len(user_agent) > 30 else (user_agent or "Unknown")

        msg_parts = [
            f"[{method}] {domain}",
            f"Status: {status_code}",
            f"Latency: {latency_ms:.0f}ms",
            f"Proxy: {p_mask}",
            f"UA: {ua_mask}",
            f"Retries: {retries}"
        ]
        
        if proxy_rotated:
            msg_parts.append("ROTATED")
        if proxy_failed:
            msg_parts.append(f"FAILED (Cooldown: {cooldown}s)")

        msg = " | ".join(msg_parts)
        
        if 200 <= status_code < 300 and not proxy_failed:
            logger_instance.info(msg)
        elif 300 <= status_code < 400 and not proxy_failed:
            logger_instance.info(f"Redirect: {msg}")
        elif (400 <= status_code < 500) or proxy_failed:
            logger_instance.warning(f"Client/Proxy Error: {msg}")
        else:
            logger_instance.error(f"Server Error: {msg}")
