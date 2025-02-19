from __future__ import annotations

from .. import settings
from ..migrations import auto, migrate
from .base import AppCommand, BaseCommand, FuncCommand


class Command(BaseCommand):
    'Migration commands'

    class Migrate(FuncCommand(migrate, AppCommand)):

        @classmethod
        def add_arguments(cls, parser):
            parser.add_argument('--auto-only', action='store_true', help='Only run if DB_AUTO_MIGRATE=true')
            super().add_arguments(parser)

    class Auto(FuncCommand(auto, AppCommand)):

        @classmethod
        def add_arguments(cls, parser):
            parser.add_argument('--message', '-m', default='auto', help='Migration message, default auto')
            super().add_arguments(parser)

    class Alembic(BaseCommand):

        @classmethod
        def init_parser(cls, parser):
            for action in CommandLine().parser._actions:
                if action.dest in ('help', 'config'):
                    continue
                parser._add_action(action)

        def setup(self, opts):
            if not hasattr(opts, 'cmd'):
                self.parser.error('too few arguments')
            self.config = Config(settings.ALEMBIC_INI, ini_section=opts.name, cmd_opts=opts)

        def run(self):
            CommandLine().run_cmd(self.config, self.opts)

    commands = dict(migrate=Migrate, auto=Auto, alembic=Alembic)

try:
    from alembic.config import CommandLine, Config
except ModuleNotFoundError:
    Command.commands.pop('alembic')