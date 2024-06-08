from __future__ import annotations

import alembic.command
from alembic.config import Config

from .. import settings
from ..orm import engine, load_naics
from ..utils import BaseCommand


def migrate() -> None:
    config = Config(settings.ALEMBIC_INI)
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        alembic.command.upgrade(config, 'head')
    load_naics(if_not_exists=True)

class Command(BaseCommand):
    'Run schema migrations'

    def run(self):
        migrate()

if __name__ == '__main__':
    Command.main()
