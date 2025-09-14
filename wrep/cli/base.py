from __future__ import annotations

import argparse
import asyncio
import enum
from typing import Any, ClassVar, Sequence

from pydantic import ConfigDict, Field

from .. import utils
from ..models import DataModel
from ..tools import asyn
from .formatters import SmartFormatter

type AP = argparse.ArgumentParser
type SubParsers = argparse._SubParsersAction[AP]

class LogLevelEnum(enum.StrEnum):
    CRITICAL = 'CRITICAL'
    FATAL = 'FATAL'
    ERROR = 'ERROR'
    WARNING = 'WARNING'
    INFO = 'INFO'
    DEBUG = 'DEBUG'

    @classmethod
    def _missing_(cls, value):
        value = str(value).upper()
        if value == 'WARN':
            value = 'WARNING'
        if value in cls:
            return cls(value)

class BaseCommandOpts(DataModel):
    log_level: LogLevelEnum|None = Field(None, exclude=True)
    model_config: ClassVar = ConfigDict(extra='allow')

class BaseCommand[O: BaseCommandOpts]:
    description: ClassVar[str|None] = None
    prog: ClassVar[str|None] = None
    usage: ClassVar[str|None] = None
    parser_class: ClassVar[type[AP]] = argparse.ArgumentParser
    formatter_class: ClassVar[type[argparse.HelpFormatter]] = SmartFormatter
    options_class: ClassVar[type[O]] = BaseCommandOpts
    commands: ClassVar[dict[str, type[BaseCommand]]] = {}
    command_metavar: ClassVar[str] = 'command'
    command_name: str|None = None
    command: BaseCommand|None = None
    opts: O

    @classmethod
    def create_parser(cls) -> AP:
        parser = cls.parser_class()
        cls.init_parser(parser)
        return parser

    @classmethod
    def init_parser(cls, parser: AP) -> None:
        parser.formatter_class = cls.formatter_class
        parser.description = cls.description
        parser.prog = cls.prog or parser.prog
        parser.usage = cls.usage or parser.usage
        cls.add_arguments(parser)
        cls.add_commands(parser)
        fmt = cls.parser_fmtargs(parser)
        if parser.description:
            parser.description = parser.description.format(**fmt)
        if parser.usage:
            parser.usage = parser.usage.format(**fmt)

    @classmethod
    def add_arguments(cls, parser: AP) -> None:
        pass

    @classmethod
    def add_commands(cls, parser: AP) -> None:
        if not cls.commands:
            return
        subparsers = cls.create_subparsers(parser)
        for name, cmd in cls.commands.items():
            subparser = subparsers.add_parser(name)
            cmd.init_parser(subparser)
            if not subparser.description:
                subparser.description = f'{name} command'

    @classmethod
    def create_subparsers(cls, parser: AP) -> SubParsers:
        return parser.add_subparsers(
            dest=cls.command_opt,
            metavar=cls.command_metavar,
            help=', '.join(cls.commands),
            required=True)

    @classmethod
    def parser_fmtargs(cls, parser: AP) -> dict[str, Any]:
        return dict(prog=parser.prog)

    @classmethod
    def main(cls, args: Sequence[str]|None = None) -> None:
        parser = cls.create_parser()
        cmd = cls(parser.parse_args(args), parser)
        asyncio.run(asyn.wait(cmd.run()))

    def __init__(self, nsargs: argparse.Namespace, parser: AP) -> None:
        self.nsargs = nsargs
        self.nsvars: dict[str, Any] = vars(nsargs)
        self.opts: O = self.options_class.model_validate(self.nsvars)
        self.parser = parser
        if hasattr(nsargs, self.command_opt):
            self.command_name = getattr(nsargs, self.command_opt)
            delattr(nsargs, self.command_opt)
            self.command = self.commands[self.command_name](nsargs, parser)
        else:
            self.setup()

    def setup(self) -> None:
        pass

    async def run(self) -> None:
        if self.command:
            await asyn.wait(self.command.run())

    def __init_subclass__(cls) -> None:
        cls.command_opt = f'_command_{abs(hash(cls))}'
        cls.description = (
            cls.__dict__.get('description') or
            cls.__doc__ or
            cls.description)

def FuncCommand(f, *bases: type[BaseCommand]) -> type[BaseCommand]:
    class Base(BaseCommand[BaseCommandOpts]):
        func = staticmethod(f)

        async def run(self) -> None:
            await asyn.wait(self.func(**self.opts.model_dump()))

    class Command(*bases, Base):
        description = f.__doc__

    return Command

class AppCommand[O: BaseCommandOpts](BaseCommand[O]):

    def setup(self):
        super().setup()
        if self.opts.log_level:
            from .. import settings
            if settings.LOG_LEVEL != self.opts.log_level:
                settings.LOG_LEVEL = self.opts.log_level
                utils.init_logging()

    @classmethod
    def add_arguments(cls, parser: AP) -> None:
        parser.add_argument(
            '--log-level',
            metavar='level',
            help=f'Log level')
        super().add_arguments(parser)
