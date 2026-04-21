# MongoDB Migration runbook and manual

## What has changed?
The Tesco Price Tracker now utilizes **MongoDB** as its primary data store instead of a filesystem filled with JSON files.
The project exposes a new REST API powered by **FastAPI** to serve both the legacy browser extensions natively, and the modern UI or updated extensions.

### Core components
- **MongoDB** stores all product configurations, mapping 1:1 the exact schema previously held in `./data/*.json`.
- **FastAPI (`app.py`)** serves queries, retaining the exact JSON structure for old extension backwards-compatibility without issues.
- **`database_manager.py`** has been fully updated to interact directly with the single Mongo collection via `pymongo`, resolving thread safety race conditions immediately.
- **Run State Tracking**: `run_state.json` now logs into the `runs` Mongo collection.
- Tests (under `tests/test_period_folding.py`) validate identical fold behavior.

## How do I connect to MongoDB?

### 1. Connecting Programmatically or locally
Because MongoDB is mapped to port `50200` in the `docker-compose.yml`, you can use any GUI like **MongoDB Compass** or local `mongosh` via the URI:
`mongodb://admin:secretpassword@localhost:50200/`

(Note: Ensure you update the username and password explicitly if you've changed the matching rules in your `.env`!)

### 2. The Built-in Web UI (Mongo Express)
A lightweight web-based interface, **Mongo Express**, has been included in your Docker configuration. It gives you raw read/write capability to your datasets out-of-the-box.

**How to Use:**
1. Once the services start (via `docker-compose up -d` or `docker stack deploy`), navigate to **http://localhost:50201** in your browser.
2. When prompted for HTTP Basic Auth, log in (default credentials are `admin` / `secretpassword`, derived from `.env` or Compose variables).
3. Select the `tesco_tracker` database.
4. Access the `products` collection to see exactly what products exist, verify pricing metadata, and edit directly if manual intervention is suddenly required.
5. Access the `runs` collection to check the advisory tracker log that reports any scraping issues.

### 3. Stack Deployment Scenario (Docker Swarm / Portainer)
When deploying this as a Docker Swarm stack or within Portainer, ensure you configure the environment variables properly:
1. **Environment Variables**: Add the contents of your `.env` directly to the Portainer stack environment tab, or deploy via CLI with `docker stack deploy -c docker-compose.yml tesco-tracker`.
2. **Volumes**: The `mongo_data` volume will be created at the cluster level. For multi-node environments, ensure you either pin the DB to a specific node (via placement constraints) or use a distributed storage driver to prevent data loss if the container shifts.
3. **Internal Routing**: Services (`api`, `scheduler`, `mongo-express`) address the database automatically via the `mongo` host moniker across the internal Docker overlay network.

### Initial Cutover Backfill
Before disabling your current scraper instance or deleting data files:
Run the script below to ingest the existing static files into the DB:
```bash
python scripts/backfill_mongo.py
```
Wait for verification and tests to pass, then delete/hide the `data/` backup structure.
