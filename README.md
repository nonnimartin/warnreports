# warn_reporter

- Create virtual env: `virtualenv .venv`
- Activate virtual env: `source .venv/bin/activate`
- Create `.env` file. See [.env.example](/.env.example) and [settings.py](/settings.py)
- Install requirements: `pip install -r requirements.txt`
- Install warn-scraper: `./scripts/install-warn-scraper.sh`
- Create schema: `python -m models migrate`
- Run service: `uvicorn main:app --reload`
