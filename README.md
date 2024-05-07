# warn_reporter

## Install

### Installing locally

```sh
# Create virtual env
virtualenv -p 3.12 .venv

# Activate virtual env
source .venv/bin/activate

# Install requirements
python -m pip install -r requirements.txt

# Install warn-scraper
./scripts/install-warn-scraper.sh
```

Optional:

- Create `.env` file. See [.env.example](/.env.example) and [settings.py](/wrep/settings.py).

Example commands:

```sh
# Create schema
python -m wrep.models migrate

# Run server
python -m wrep.main

# Pipeline
python -m wrep.pipeline -h

# Notifications
python -m wrep.notify
```

### Using docker compose

The compose config includes MongoDB.

```sh
docker compose build
docker compose up -d
```

Example commands:

```sh
# Create schema
docker compose exec app python -m wrep.models migrate

# Clean and build index
docker compose exec app python -m wrep.models build_index

# Run index pipeline stage
docker compose exec app python -m wrep.pipeline index
```

Mongo Express is available at http://127.0.0.1:8081/