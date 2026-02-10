import os
from dotenv import load_dotenv
import logging

# Load environment variables from .env file
load_dotenv()

API_URL = 'https://xapi.tesco.com/v1/graphql'
API_KEY = os.getenv('API_KEY')

# Log the API key being used (first 5 characters only)
if API_KEY:
    logger = logging.getLogger(__name__)
    logger.info(f"API Key loaded: {API_KEY[:5]}..." if len(API_KEY) > 5 else "API Key loaded (too short)")
else:
    logger = logging.getLogger(__name__)
    logger.warning("WARNING: API_KEY not found in environment variables! Check your .env file.")

HEADERS = {
    'Accept': 'application/json',
    'content-type': 'application/json',
    'region': 'HU',
    'language': 'hu-HU',
    'x-apikey': API_KEY,
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

SITEMAP_INDEX_URL = 'https://bevasarlas.tesco.hu/sitemaps/hu-HU/groceries/products-index.xml'
