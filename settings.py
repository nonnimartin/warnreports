from os import getenv
from os.path import dirname

import dotenv

dotenv.load_dotenv()

BASEDIR = dirname(__file__)
SEED = getenv('SEED', 'insecure_2x^3ubxMqN6Tj3BVe4KP!XfTKpW$asYP')
EMAIL_ACCOUNT = getenv('EMAIL_ACCOUNT', 'you@somewhere.example')
SITE_URL = getenv('SITE_URL', 'http://localhost:8000')
DB_URL = getenv('DB_URL', f'sqlite:///{BASEDIR}/db.sqlite')
REPORTS_DIR = getenv('REPORTS_DIR', f'{BASEDIR}/build/reports')
WARN_OUTPUT_DIR = getenv('WARN_OUTPUT_DIR', f'{BASEDIR}/build/warn')
WARN_DATA_DIR = f'{WARN_OUTPUT_DIR}/exports'
WARN_CACHE_DIR = f'{WARN_OUTPUT_DIR}/cache'
CONVERSIONS_FILE = f'{BASEDIR}/res/conversions.json'
