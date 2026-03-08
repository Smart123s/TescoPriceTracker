import os
import sys
import logging
from dotenv import load_dotenv

# Load environment variables from .env (simple, explicit)
load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data directory resolution: env var → virtualenv fallback → error
# ---------------------------------------------------------------------------
DATA_FOLDER_ENV = os.getenv('DATA_FOLDER', '/app/data')
if DATA_FOLDER_ENV:
    DATA_DIR = os.path.abspath(DATA_FOLDER_ENV)
else:
    venv_path = os.getenv('VIRTUAL_ENV') or (
        sys.prefix if getattr(sys, 'base_prefix', sys.prefix) != sys.prefix else None
    )
    if venv_path:
        DATA_DIR = os.path.abspath(os.path.join(venv_path, 'data'))
    else:
        print("Error: no DATA_FOLDER env var set and no virtualenv detected. "
              "Please set DATA_FOLDER to a valid path.")
        sys.exit(1)

# ---------------------------------------------------------------------------
# Scraper / threading defaults
# ---------------------------------------------------------------------------
DEFAULT_THREADS = 2

# ---------------------------------------------------------------------------
# Scheduler settings
# ---------------------------------------------------------------------------
SCHEDULER_CRON = '0 5 * * *'
SCHEDULER_TIMEZONE = 'Europe/Budapest'

# ---------------------------------------------------------------------------
# Tesco API
# ---------------------------------------------------------------------------
API_URL = 'https://xapi.tesco.com/v1/graphql'
API_KEY = os.getenv('API_KEY')

if API_KEY:
    logger.info(f"API Key loaded: {API_KEY[:5]}..." if len(API_KEY) > 5 else "API Key loaded (too short)")
else:
    logger.warning("WARNING: API_KEY not found in environment variables or .env file!")

HEADERS = {
    'Accept': 'application/json',
    'content-type': 'application/json',
    'region': 'HU',
    'language': 'hu-HU',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

if API_KEY:
    HEADERS['x-apikey'] = API_KEY

SITEMAP_INDEX_URL = 'https://bevasarlas.tesco.hu/sitemaps/hu-HU/groceries/products-index.xml'
