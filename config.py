import os
from dotenv import load_dotenv

load_dotenv()


SEARCH_ENGINE = os.getenv("SEARCH_ENGINE", "googlesearch")

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")


MAX_COMPANIES_PER_QUERY = 10
MAX_RETRIES = 3
REQUEST_DELAY = 2
REQUEST_TIMEOUT = 10

# ------------------------
# Paths
# ------------------------

OUTPUT_FOLDER = "output"
DATA_FOLDER = "data"