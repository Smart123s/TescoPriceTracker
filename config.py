import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env (simple, explicit)
load_dotenv()

API_URL = 'https://xapi.tesco.com/v1/graphql'
API_KEY = os.getenv('API_KEY')
logger = logging.getLogger(__name__)

if API_KEY:
    logger.info(f"API Key loaded: {API_KEY[:5]}..." if len(API_KEY) > 5 else "API Key loaded (too short)")
else:
    logger.warning("WARNING: API_KEY not found in environment variables or .env file!")

# Build headers and only include the API key header when present
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
