from os import getenv
from pathlib import Path
from uuid import UUID

BASEDIR = Path(__file__).parent
REPODIR = BASEDIR.parent
STATIC_DIR = BASEDIR/'static'
TEMPLATES_DIR = BASEDIR/'templates'
NAICS_DOWNLOAD = 'https://github.com/owings1/naics/raw/2022-1/build/2022.min.json'
BUILD_DIR = Path(getenv('BUILD_DIR', REPODIR/'build'))
LOG_LEVEL = getenv('LOG_LEVEL', 'INFO').upper()
SEED = getenv('SEED', 'insecure_2x^3ubxMqN6Tj3BVe4KP!XfTKpW$asYP')
NAMESPACE = UUID(getenv('NAMESPACE', 'b98ba54b-c67b-4bce-b609-b2a236e33b14'))
DB_URL = getenv('DB_URL', f'sqlite:///{REPODIR}/db.sqlite')
MONGODB_ENABLED = getenv('MONGODB_ENABLED', '').lower() == 'true'
MONGODB_URL = getenv('MONGODB_URL', 'mongodb://localhost:27017/')
SEARCH_BACKEND = getenv('SEARCH_BACKEND', 'sql')
SITE_URL = getenv('SITE_URL', 'http://localhost:8000')
EMAIL_BACKEND = getenv('EMAIL_BACKEND', 'ses')
EMAIL_ACCOUNT = getenv('EMAIL_ACCOUNT', 'you@somewhere.example')
