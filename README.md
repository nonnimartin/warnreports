# warn_reporter

## Install

```sh
# Create virtual env
virtualenv -p 3.12 .venv

# Activate virtual env
source .venv/bin/activate

# Install requirements
python -m pip install -r requirements.txt

# Install warn-scraper
./scripts/install-warn-scraper.sh

# Create schema
python -m wrep.models migrate
```

Optional:

- Create `.env` file. See [.env.example](/.env.example) and [settings.py](/wrep/settings.py).

## Run

```sh
# Server
python -m wrep.main

# Pipeline
python -m wrep.pipeline -h

# Notifications
python -m wrep.notify
```
