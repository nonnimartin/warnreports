from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from .. import settings
from .base import AppCommand, AppCommandOpts, BaseCommandOpts


class MigrateOpts(AppCommandOpts):
    auto_only: bool = Field(description='Only run if DB_AUTO_MIGRATE=true')

class AutoOpts(AppCommandOpts):
    message: str = Field('auto', description='Migration message, default auto')

class AlembicOpts(BaseCommandOpts):
    model_config: ClassVar = dict(extra='allow')

class Migrate(AppCommand[MigrateOpts]):
    'Run schema migrations'
    options_class: ClassVar = MigrateOpts

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument('--auto-only')
        super().add_arguments(parser)

    def run(self):
        from ..migrations import migrate
        migrate(**self.opts.model_dump())

class Auto(AppCommand[AutoOpts]):
    'Auto-generate schema migration'
    options_class: ClassVar = AutoOpts

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument('--message', '-m')
        super().add_arguments(parser)

    def run(self):
        from ..migrations import auto
        auto(**self.opts.model_dump())

class Alembic(AppCommand[AlembicOpts]):
    options_class: ClassVar = AlembicOpts

    @classmethod
    def add_arguments(cls, parser):
        for action in CommandLine().parser._actions:
            if action.dest in ('help', 'config'):
                continue
            parser._add_action(action)

    def setup(self):
        if not hasattr(self.opts, 'cmd'):
            self.parser.error('too few arguments')
        self.config = Config(settings.ALEMBIC_INI, ini_section=self.opts.name, cmd_opts=self.opts)

    def run(self):
        CommandLine().run_cmd(self.config, self.opts)

commands = dict(
    _description='Migration commands',
    migrate=Migrate,
    auto=Auto,
    alembic=Alembic)

try:
    from alembic.config import CommandLine, Config
except ModuleNotFoundError:
    commands.pop('alembic')