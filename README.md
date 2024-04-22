# warn_reporter

- Create `.env` file. See [.env.example](/.env.example) and [settings.py](/settings.py)
- Install requirements: `pip install -r requirements.txt`
- Create schema: `sqlite3 warnDb.db < db_def`
- Run service: `uvicorn main:app --reload`
