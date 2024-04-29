from os import getenv
from pathlib import Path
import dotenv

dotenv.load_dotenv()

BASEDIR = Path(__file__).parent
LOG_LEVEL = getenv('LOG_LEVEL', 'INFO').upper()
SEED = getenv('SEED', 'insecure_2x^3ubxMqN6Tj3BVe4KP!XfTKpW$asYP')
DB_URL = getenv('DB_URL', f'sqlite:///{BASEDIR}/db.sqlite')
SITE_URL = getenv('SITE_URL', 'http://localhost:8000')
EMAIL_BACKEND = getenv('EMAIL_BACKEND', 'ses')
EMAIL_ACCOUNT = getenv('EMAIL_ACCOUNT', 'you@somewhere.example')
PIPELINE_DIR = Path(getenv('PIPELINE_DIR', BASEDIR/'build'))
CONVERSIONS_FILE = BASEDIR/'res'/'conversions.json'
TEMPLATES_DIR = BASEDIR/'templates'
