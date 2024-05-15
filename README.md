# warn_reporter

## Install

### Using docker compose

The compose config includes MongoDB.

```sh
docker compose build
docker compose up -d
```

App runs on port 8000, e.g. http://127.0.0.1:8000/

Mongo Express is available at http://127.0.0.1:8081/

Example commands:

```sh
# Create schema
docker compose exec app wrep models migrate

# Load NAICS data
docker compose exec app wrep models naics

# Run pipeline
docker compose exec app wrep pipeline all
```

