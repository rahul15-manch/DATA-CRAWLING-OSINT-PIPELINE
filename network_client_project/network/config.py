from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, validator
from typing import List, Optional
import os

class NetworkConfig(BaseSettings):
    """
    Centralized configuration for the Network Client.
    Automatically loads from environment variables or a .env file.
    """
    
    # --- PROXY SETTINGS ---
    # Can be a comma-separated string in the .env file, which Pydantic can parse into a list
    PROXIES: List[str] = Field(default_factory=list, description="List of proxy URLs")
    PROXY_FILE: Optional[str] = Field(default=None, description="Path to a file containing proxies")
    
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
