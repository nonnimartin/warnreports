from os import getenv
from pathlib import Path
from uuid import UUID

BASEDIR = Path(__file__).parent
REPODIR = BASEDIR.parent
LOG_LEVEL = getenv('LOG_LEVEL', 'INFO').upper()
SEED = getenv('SEED', 'insecure_2x^3ubxMqN6Tj3BVe4KP!XfTKpW$asYP')
NAMESPACE = UUID(getenv('NAMESPACE', 'b98ba54b-c67b-4bce-b609-b2a236e33b14'))
DB_URL = getenv('DB_URL', f'sqlite:///{REPODIR}/db.sqlite')
SITE_URL = getenv('SITE_URL', 'http://localhost:8000')
EMAIL_BACKEND = getenv('EMAIL_BACKEND', 'ses')
EMAIL_ACCOUNT = getenv('EMAIL_ACCOUNT', 'you@somewhere.example')
BUILD_DIR = Path(getenv('BUILD_DIR', REPODIR/'build'))
TEMPLATES_DIR = BASEDIR/'templates'
STATIC_DIR = BASEDIR/'static'
