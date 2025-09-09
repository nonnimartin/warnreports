from enum import StrEnum

import dotenv

dotenv.load_dotenv()

from . import utils

utils.init_logging()

from . import settings

if settings.SENTRY_ENABLED and settings.SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENVIRONMENT,
        auto_session_tracking=False)

class Stage(StrEnum):
    Scrape = 'scrape'
    Extract = 'extract'
    Translate = 'translate'
    Load = 'load'
    Index = 'index'

class SaveType(StrEnum):
    Create = 'create'
    Update = 'update'
    Nochange = 'nochange'
    Skip = 'skip'

__all__ = ()
