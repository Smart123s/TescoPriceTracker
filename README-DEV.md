# Tesco Price Tracker - Developer Info

## Architecture Overview
- **Scraper (`scraper.py`)**: A purely multithreaded Python script that fetches product pricing from the Tesco GraphQL API. It checks `needs_scraping` daily to avoid redundant API hits.
- **Database Engine (`database_manager.py`)**: Utilizes **MongoDB** (`pymongo`). It merges consecutive identical daily prices into `[start_date, end_date]` periods (referred to as "period-folding") for `normal`, `discount`, and `clubcard` categories.
- **API (`app.py`)**: A **FastAPI** service replacing the legacy file-server. It exposes the raw Mongo objects and maintains a backward-compatible shim (`/{tpnc}.json`) so legacy browser extensions remain functional.
- **Scheduler (`scheduler.py`)**: Cron-based runner executing the scraper inside a dedicated Docker container.

## Port Bindings & Infrastructure
The stack is containerized via `docker-compose.yml` and bound to the `50200-50150` range to avoid host conflicts:
- **`50200` - MongoDB**: Core database.
- **`50201` - Mongo Express**: Web-based GUI for rapid database inspection.
- **`50202` - FastAPI**: The REST API endpoints.

## Local Setup & Execution
1. Initialize environment variables:
   ```bash
   cp .env.example .env
   ```
   *Make sure to insert your Tesco `API_KEY`.*
2. Start the Docker stack locally:
   ```bash
   docker-compose up -d
   ```
   **OR via Docker Swarm / Portainer Stack**:
   Load your environment variables directly into the Portainer UI or use the CLI:
   ```bash
   # Make sure .env is populated correctly before deployment
   docker stack deploy -c docker-compose.yml tescotracker
   ```
   *(Note: Ensure you set a placement constraint for the MongoDB container or map its volume carefully if your Swarm contains multi-node clustering.)*

3. *(Migration only)* If migrating from legacy flat JSON files, run the backfill:
   ```bash
   python scripts/backfill_mongo.py
   ```

### APIs & Swagger Documentation
Thanks to FastAPI, interacting with and testing the APIs is incredibly easy.
1. Start the stack.
2. Navigate to **http://localhost:50202/docs** to see the **interactive Swagger UI** generated live from the Python endpoints. Here you can execute trial queries against the MongoDB container without needing Postman.
3. If you want the raw OpenAPI schema to generate client SDKs, navigate to **http://localhost:50202/openapi.json**.

Additionally, a static `swagger.yaml` has been provided in the repository root outlining the core schema boundaries for offline viewing.

## Connecting to the Database
MongoDB requires authentication. Assuming default `.env` configuration:
- **Programmatic / Compass URI**: `mongodb://admin:secretpassword@localhost:50200/`
- **Web UI (Mongo Express)**: Open `http://localhost:50201` in a browser. Standard HTTP Basic Auth will prompt for `admin` / `secretpassword`.

## Development & Testing
Period-folding logic is load-bearing. Any modifications to how `start_date` and `end_date` bounds behave must pass the pytest suite:
```bash
pytest tests/test_period_folding.py
```
