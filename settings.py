from os import getenv
from os.path import dirname

import dotenv

dotenv.load_dotenv()

BASEDIR = dirname(__file__)
SEED = getenv('SEED', 'insecure_2x^3ubxMqN6Tj3BVe4KP!XfTKpW$asYP')
EMAIL_ACCOUNT = getenv('EMAIL_ACCOUNT', 'you@somewhere.example')
SITE_URL = getenv('SITE_URL', 'http://localhost:8000')
DB_FILE = getenv('DB_FILE', f'{BASEDIR}/warnDb.db')
REPORTS_DIR = getenv('REPORTS_DIR', f'{BASEDIR}/reports_json')
