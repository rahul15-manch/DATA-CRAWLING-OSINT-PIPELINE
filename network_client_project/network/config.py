from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, validator
from typing import List, Optional, Union
import os

class NetworkConfig(BaseSettings):
    """
    Centralized configuration for the Network Client.
    Automatically loads from environment variables or a .env file.
    """
    
    # --- PROXY SETTINGS ---
    # Can be a comma-separated string in the .env file
    PROXIES: Union[str, List[str]] = Field(default="", description="Comma-separated list or List of proxy URLs")
    PROXY_URL: Optional[str] = Field(default=None, description="Single proxy URL")
    PROXY_FILE: Optional[str] = Field(default=None, description="Path to a file containing proxies")

    @validator("PROXY_FILE", pre=True, always=True)
    def default_proxy_file(cls, v):
        if not v:
            if os.path.exists("working_proxies.txt"):
                return "working_proxies.txt"
            return "proxies.txt"
        if v == "proxies.txt" and os.path.exists("working_proxies.txt"):
            return "working_proxies.txt"
        return v

    # --- GOOGLE SCHEDULER SETTINGS ---
    GOOGLE_MAX_CONCURRENT: int = Field(default=2)
    GOOGLE_REQUEST_BUDGET: int = Field(default=6)
    GOOGLE_DELAY_MIN: float = Field(default=2.0)
    GOOGLE_DELAY_MAX: float = Field(default=6.0)
    GOOGLE_CAPTCHA_COOLDOWN: float = Field(default=1800.0)
    GOOGLE_429_COOLDOWN: float = Field(default=900.0)
    GOOGLE_PROXY_SCORE_THRESHOLD: float = Field(default=10.0)

    # --- SEARCH CACHE SETTINGS ---
    ENABLE_SEARCH_CACHE: bool = Field(default=True)
    SEARCH_CACHE_TTL: int = Field(default=86400)
    SEARCH_CACHE_FILE: str = Field(default="search_cache.json")
    GOOGLE_MAX_PROXY_RETRIES: int = Field(default=5)
    GOOGLE_FAILURE_CACHE_TTL: int = Field(default=600)
    MIN_REUSE_INTERVALS: dict = Field(default_factory=lambda: {"google": 15.0, "bing": 3.0, "default": 0.0})



    @property
    def get_all_proxies(self) -> List[str]:
        """Combines PROXIES and PROXY_URL without duplicates."""
        proxies_set = set()
        if self.PROXIES:
            if isinstance(self.PROXIES, str):
                proxies_set.update([p.strip() for p in self.PROXIES.split(",") if p.strip()])
            else:
                proxies_set.update(self.PROXIES)
        if self.PROXY_URL:
            proxies_set.add(self.PROXY_URL)
        return list(proxies_set)



    
    # --- RETRY & TIMEOUT SETTINGS ---
    MAX_RETRIES: int = Field(default=3, description="Maximum number of retry attempts per request")
    CONNECT_TIMEOUT: float = Field(default=10.0, description="Seconds to wait for TCP handshake")
    READ_TIMEOUT: float = Field(default=30.0, description="Seconds to wait for first byte of response")
    
    # --- RATE LIMITING & DELAYS ---
    GLOBAL_RATE_LIMIT: float = Field(default=10.0, description="Global max requests per second")
    MIN_DELAY: float = Field(default=1.0, description="Minimum human delay in seconds")
    MAX_DELAY: float = Field(default=3.5, description="Maximum human delay in seconds")
    
    # --- LOGGING ---
    LOG_LEVEL: str = Field(default="INFO", description="DEBUG, INFO, WARNING, ERROR, CRITICAL")
    LOG_DIR: str = Field(default="logs", description="Directory to store log files")
    
    # --- FINGERPRINTING ---
    FALLBACK_USER_AGENT: str = Field(
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        description="Used if fake_useragent fails"
    )

    # --- SSL ---
    VERIFY_SSL: bool = Field(default=True, description="Verify SSL certificates")

    # Configure Pydantic to read from a .env file if it exists
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        case_sensitive=True,
        extra="ignore" # Ignore extra variables in .env that belong to other teams
    )

    @property
    def timeout_tuple(self):
        """Returns the tuple expected by requests.get(timeout=...)"""
        return (self.CONNECT_TIMEOUT, self.READ_TIMEOUT)

# Instantiate a global config object that the rest of the application can import
config = NetworkConfig()
