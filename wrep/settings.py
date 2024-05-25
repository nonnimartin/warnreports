from os import getenv
from pathlib import Path
from uuid import UUID

BASEDIR = Path(__file__).parent
REPODIR = BASEDIR.parent
STATIC_DIR = BASEDIR/'static'
TEMPLATES_DIR = BASEDIR/'templates'
ALEMBIC_INI = REPODIR/'alembic.ini'
BUILD_DIR = Path(getenv('BUILD_DIR', REPODIR/'build'))
ARTIFACTS_DIR = Path(getenv('ARTIFACTS_DIR', BUILD_DIR/'artifacts'))
NAICS_DOWNLOAD = 'https://github.com/owings1/naics/raw/2022-1/build/2022.min.json'
LOG_LEVEL = getenv('LOG_LEVEL', 'INFO').upper()
QUERY_LOGGING = getenv('QUERY_LOGGING', '').lower() == 'true'
NAMESPACE = UUID(getenv('NAMESPACE', 'b98ba54b-c67b-4bce-b609-b2a236e33b14'))
DB_URL = getenv('DB_URL', f'sqlite:///{REPODIR}/db.sqlite')
DB_AUTO_MIGRATE = getenv('DB_AUTO_MIGRATE', 'true').lower() == 'true'
MONGODB_URL = getenv('MONGODB_URL', 'mongodb://localhost:27017/')
MONGODB_DBNAME = getenv('MONGODB_DBNAME', 'active')
ETL_MONGODB_URL = getenv('ETL_MONGODB_URL', MONGODB_URL)
ETL_MONGODB_DBNAME = getenv('ETL_MONGODB_DBNAME', MONGODB_DBNAME)
SITE_URL = getenv('SITE_URL', 'http://localhost:8000')
EMAIL_BACKEND = getenv('EMAIL_BACKEND', 'ses')
EMAIL_FROM_ADDRESS = getenv('EMAIL_FROM_ADDRESS', 'you@somewhere.example')
FEED_ENTRY_LIMIT = int(getenv('FEED_ENTRY_LIMIT', 100))
SENTRY_ENABLED = getenv('SENTRY_ENABLED', '').lower() == 'true'
SENTRY_DSN = getenv('SENTRY_DSN', '')
SENTRY_ENVIRONMENT = getenv('SENTRY_ENVIRONMENT', 'dev')