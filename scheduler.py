import time
import logging
import os
import pycron
from datetime import datetime
import pytz
from scraper import run_scraper, is_today_scrape_done

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Timezone
TZ_NAME = 'Europe/Budapest' # CET/CEST

def now_in_tz():
    return datetime.now(pytz.timezone(TZ_NAME))

def job():
    logger.info("Starting scheduled scrape job...")
    try:
        # Run scraper logic
        run_scraper(threads=5) 
        logger.info("Scrape job finished.")
    except Exception as e:
        logger.error(f"Error during scrape job: {e}")

if __name__ == "__main__":
    # 1. Run immediately on startup if today's run isn't already done
    logger.info("Container started. Checking today's run state...")
    if not is_today_scrape_done():
        logger.info("Today's run not found — running initial scrape...")
        job()
        logger.info("Initial scrape complete.")
    else:
        logger.info("Today's scrape already completed — skipping initial run.")

    logger.info("Entering scheduler loop (Daily at 05:00 CET).")

    while True:
        # Check every minute if it matches 05:00
        # pycron.is_now checks if the current time matches the cron pattern.
        # We need to pass the current time in the correct timezone.

        current_time = now_in_tz()

        # '0 5 * * *' run at 5:00 AM
        if pycron.is_now('0 5 * * *', dt=current_time):
            if not is_today_scrape_done():
                job()
            else:
                logger.info("Scheduled run skipped — today's scrape already completed.")

            # Sleep for more than a minute to avoid double triggering if execution is super fast
            time.sleep(60)

        time.sleep(20) # Check 3 times a minute to be sure we catch the minute '05:00'
