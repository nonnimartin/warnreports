from os import getenv

from wrep.settings import REPODIR
from wrep.settings import SITE_URL as SITE_URL

USERS_DB_URL = getenv('USERS_DB_URL', f'sqlite:///{REPODIR}/db.users.sqlite')
