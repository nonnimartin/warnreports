from __future__ import annotations

import argparse
import asyncio
import enum
from collections import ChainMap
from types import UnionType
from typing import Any, ClassVar, Iterable, Sequence

from pydantic import ConfigDict, Field
from pydantic_core import PydanticUndefinedType

from .. import settings, utils
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
    pass

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
    def main(cls, args: Sequence[str]|None = None) -> None:
        "Main CLI entrypoint"
        parser = cls.create_parser()
        cmd = cls(parser.parse_args(args), parser)
        asyncio.run(asyn.wait(cmd.run()))

    @classmethod
    def create_parser(cls) -> AP:
        "Create the main (root) argument parser"
        parser = cls.parser_class()
        cls.init_parser(parser)
        return parser

    @classmethod
    def init_parser(cls, parser: AP) -> None:
        "Setup the parser this command/subcommand"
        parser.formatter_class = cls.formatter_class
        parser.description = cls.description
        parser.prog = cls.prog or parser.prog
        parser.usage = cls.usage or parser.usage
        cls.add_arguments(parser)
        cls.extend_actions(parser)
        cls.add_commands(parser)
        fmtargs = cls.parser_fmtargs(parser)
        if parser.description:
            parser.description = parser.description.format(**fmtargs)
        if parser.usage:
            parser.usage = parser.usage.format(**fmtargs)

    @classmethod
    def add_arguments(cls, parser: AP) -> None:
        "Add the command's specific arguments to the parser"
        pass

    @classmethod
    def extend_actions(cls, parser: AP) -> None:
        "Autofill argument descriptions & defaults from the options DataModel fields"
        fields = ChainMap(*(
            hintcls.model_fields for hintcls
            in cls.get_action_hint_classes()))
        fmtargs = cls.parser_fmtargs(parser)
        for action in parser._actions:
            if action.const is False:
                # store_false
                continue
            if action.help or not (field := fields.get(action.dest)):
                continue
            if (text := field.description or field.title):
                action.help = text.format(**fmtargs)
            if action.default is ...:
                if not isinstance(field.default, PydanticUndefinedType):
                    action.default = field.default
            if action.choices == (...,):
                anno = field.annotation
                annoargs = anno.__args__ if isinstance(anno, UnionType) else [anno]
                for cand in annoargs:
                    if issubclass(cand, enum.Enum):
                        action.choices = list(cand)
                        break

    @classmethod
    def get_action_hint_classes(cls) -> Iterable[type[DataModel]]:
        "Allows overriding which DataModel classes to use to autofill arguments"
        yield cls.options_class

    @classmethod
    def add_commands(cls, parser: AP) -> None:
        "Setup subcommands for a container command defined in the `commands` dict"
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
        "Initialize the argument subparsers for a container command"
        return parser.add_subparsers(
            dest=cls.command_opt,
            metavar=cls.command_metavar,
            help=', '.join(cls.commands),
            required=True)

    @classmethod
    def parser_fmtargs(cls, parser: AP) -> dict[str, Any]:
        "String format() keyword args for command description & usage"
        return dict(prog=parser.prog, cls=cls)

    def __init__(self, nsargs: argparse.Namespace, parser: AP) -> None:
        self.parser = parser
        self.opts: O = self.options_class.model_validate(vars(nsargs))
        if hasattr(nsargs, self.command_opt):
            # This is a container/parent command
            self.command_name = getattr(nsargs, self.command_opt)
            delattr(nsargs, self.command_opt)
            # Initialize the subcommand
            self.command = self.commands[self.command_name](nsargs, parser)
        else:
            # This is the terminal/leaf command
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

class AppCommandOpts(BaseCommandOpts):
    log_level: LogLevelEnum|None = Field(None, exclude=True, description='Log level')
    model_config: ClassVar = ConfigDict(extra='allow')

class AppCommand[O: AppCommandOpts](BaseCommand[O]):
    options_class: type[O] = AppCommandOpts

    def setup(self):
        super().setup()
        if self.opts.log_level and settings.LOG_LEVEL != self.opts.log_level:
            settings.LOG_LEVEL = self.opts.log_level
            utils.init_logging()

    @classmethod
    def add_arguments(cls, parser: AP) -> None:
        parser.add_argument('--log-level', metavar='level')
        super().add_arguments(parser)


def FuncCommand(f, *bases: type[AppCommand]) -> type[AppCommand]:
    class Base(AppCommand[AppCommandOpts]):
        func = staticmethod(f)

        async def run(self) -> None:
            await asyn.wait(self.func(**self.opts.model_dump()))

    class Command(*bases, Base):
        description = f.__doc__

    return Command
