from __future__ import annotations

import argparse
import asyncio
from argparse import ArgumentParser, _SubParsersAction
from typing import Any, ClassVar

from .. import utils

type AP = ArgumentParser
type SubParsers = _SubParsersAction[ArgumentParser]


class HelpFormatter(argparse.HelpFormatter):
    """
    From: https://gist.github.com/panzi/b4a51b3968f67b9ff4c99459fb9c5b3d
    Author: Mathias Panzenböck
    """

    def _split_lines(self, text: str, width: int) -> list[str]:
        lines: list[str] = []
        for line_str in text.split('\n'):
            line: list[str] = []
            line_len = 0
            for word in line_str.split():
                word_len = len(word)
                line_len += word_len + bool(line)
                if line_len > width:
                    lines.append(' '.join(line))
                    line.clear()
                    line_len = word_len
                line.append(word)
            lines.append(' '.join(line))
        return lines
    
    def _fill_text(self, text: str, width: int, indent: str) -> str:
        return '\n'.join(indent + line for line in self._split_lines(text, width - len(indent)))

class BaseCommand:
    description: ClassVar[str|None] = None
    prog: ClassVar[str|None] = None
    usage: ClassVar[str|None] = None
    parser_class: ClassVar[type[AP]] = ArgumentParser
    formatter_class: ClassVar[type[argparse.HelpFormatter]] = HelpFormatter
    commands: ClassVar[dict[str, type[BaseCommand]]] = {}
    command_metavar: ClassVar[str] = 'command'
    command_name: str|None = None
    command: BaseCommand|None = None

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
    def main(cls, args=None):
        parser = cls.create_parser()
        opts = parser.parse_args(args)
        cmd = cls(opts, parser)
        asyncio.run(utils.wait(cmd.run()))

    def __init__(self, opts, parser: AP) -> None:
        self.opts = opts
        self.parser = parser
        if hasattr(opts, self.command_opt):
            self.command_name = getattr(opts, self.command_opt)
            delattr(opts, self.command_opt)
            self.command = self.commands[self.command_name](opts, parser)
        else:
            self.setup(opts)

    def setup(self, opts) -> None:
        pass

    async def run(self):
        if self.command:
            await utils.wait(self.command.run())

    def __init_subclass__(cls) -> None:
        cls.command_opt = f'_command_{abs(hash(cls))}'
        cls.description = (
            cls.__dict__.get('description') or
            cls.__doc__ or
            cls.description)

def FuncCommand(f, *bases: type[BaseCommand]) -> type[BaseCommand]:
    class Base(BaseCommand):
        func = staticmethod(f)

        async def run(self):
            await utils.wait(self.func(**vars(self.opts)))

    class Command(*bases, Base):
        description = f.__doc__

    return Command

class AppCommand(BaseCommand):

    def setup(self, opts):
        super().setup(opts)
        if opts.log_level:
            from .. import settings
            settings.LOG_LEVEL = opts.log_level
            utils.init_logging()
        del opts.log_level

    @classmethod
    def add_arguments(cls, parser: AP):
        parser.add_argument('--log-level', default=None)
        super().add_arguments(parser)
