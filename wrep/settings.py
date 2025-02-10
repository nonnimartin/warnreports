from os import getenv
from pathlib import Path
from uuid import UUID

from starlette.datastructures import URL

from .utils import deltaparse

BASEDIR = Path(__file__).parent
REPODIR = BASEDIR.parent
ALEMBIC_INI = REPODIR/'alembic.ini'
BUILD_DIR = Path(getenv('BUILD_DIR', REPODIR/'build'))
ARTIFACTS_DIR = Path(getenv('ARTIFACTS_DIR', BUILD_DIR/'artifacts'))
BOOTSTRAP_DIR = Path(getenv('BOOTSTRAP_DIR', REPODIR/'lib'/'bootstrap'))
FRONTEND_SRC = BASEDIR/'frontend'/'src'
FRONTEND_DIST = Path(getenv('FRONTEND_DIST', BUILD_DIR/'dist'))
FRONTEND_AUTO_BUILD = getenv('FRONTEND_AUTO_BUILD', '').lower() == 'true'
FRONTEND_CACHE_HTML = getenv('FRONTEND_CACHE_HTML', 'true').lower() == 'true'
NAICS_DOWNLOAD = 'https://archive.warnreports.org/naics/dist/2022-2/2022.min.json'
LOG_LEVEL = getenv('LOG_LEVEL', 'INFO').upper()
QUERY_LOGGING = getenv('QUERY_LOGGING', '').lower() == 'true'
NAMESPACE = UUID(getenv('NAMESPACE', 'b98ba54b-c67b-4bce-b609-b2a236e33b14'))
DB_URL = getenv('DB_URL', f'sqlite:///{REPODIR}/db.sqlite')
DB_AUTO_MIGRATE = getenv('DB_AUTO_MIGRATE', 'true').lower() == 'true'
MONGODB_URL = getenv('MONGODB_URL', 'mongodb://localhost:27017/')
MONGODB_DBNAME = getenv('MONGODB_DBNAME', 'active')
MONGODB_DBNAME_TTL = deltaparse(getenv('MONGODB_DBNAME_TTL', '60s'), default_unit='seconds')
MONGODB_CONTROL_DBNAME = getenv('MONGODB_CONTROL_DBNAME', 'control')
SEARCH_MONGODB_URL = getenv('SEARCH_MONGODB_URL', MONGODB_URL)
SEARCH_MONGODB_DBNAME = getenv('SEARCH_MONGODB_DBNAME', MONGODB_DBNAME)
SEARCH_MONGODB_DBNAME_TTL = deltaparse(getenv('SEARCH_MONGODB_DBNAME_TTL', MONGODB_DBNAME_TTL), default_unit='seconds')
SEARCH_MONGODB_CONTROL_DBNAME = getenv('SEARCH_MONGODB_CONTROL_DBNAME', MONGODB_CONTROL_DBNAME)
ETL_MONGODB_URL = getenv('ETL_MONGODB_URL', MONGODB_URL)
ETL_MONGODB_DBNAME = getenv('ETL_MONGODB_DBNAME', MONGODB_DBNAME)
ETL_MONGODB_DBNAME_TTL = deltaparse(getenv('ETL_MONGODB_DBNAME_TTL', MONGODB_DBNAME_TTL), default_unit='seconds')
ETL_MONGODB_CONTROL_DBNAME = getenv('ETL_MONGODB_CONTROL_DBNAME', MONGODB_CONTROL_DBNAME)
ETL_DEFAULT_WORKERS = max(1, int(getenv('ETL_DEFAULT_WORKERS', 4)))
SITE_URL = URL(getenv('SITE_URL', 'http://localhost:8000'))
EMAIL_BACKEND = getenv('EMAIL_BACKEND', 'ses')
EMAIL_FROM_ADDRESS = getenv('EMAIL_FROM_ADDRESS', 'you@somewhere.example')
FEED_ENTRY_LIMIT = int(getenv('FEED_ENTRY_LIMIT', 100))
SENTRY_ENABLED = getenv('SENTRY_ENABLED', '').lower() == 'true'
SENTRY_DSN = getenv('SENTRY_DSN', '')
SENTRY_ENVIRONMENT = getenv('SENTRY_ENVIRONMENT', 'dev')
UVICORN_RELOAD = getenv('UVICORN_RELOAD', '').lower() == 'true'
UVICORN_PROXY_HEADERS = getenv('UVICORN_PROXY_HEADERS', '').lower() == 'true'