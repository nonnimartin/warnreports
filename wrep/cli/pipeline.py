from __future__ import annotations

import logging
from pathlib import Path
from textwrap import dedent
from typing import ClassVar

from .. import Stage, settings
from .base import AppCommand, BaseCommandOpts
from .validators import StagesOpt, StatesOpt, StatesOptTa

logger = logging.getLogger(__name__)

class PipelineCommandOpts(BaseCommandOpts):
    stages: StagesOpt
    states: StatesOpt

class Command(AppCommand[PipelineCommandOpts]):
    options_class: ClassVar = PipelineCommandOpts
    description: ClassVar = dedent("""
    Run pipeline stages.
    
    Basic Examples
    --------------

    Run single stage for all states:
      {prog} scrape

    Run single stage for some states:
      {prog} extract CA NY

    Run all stages for some states:
      {prog} all FL OH

    Run all stages for all states:
      {prog} all

    Selecting Stages
    -----------------

    Available stages: """ + ', '.join(Stage) + """

    Specify multiple stages with a comma:
      {prog} scrape,extract [state ...]

    Using first letter with comma:
      {prog} s,e,t [state ...]

    With capital first letters, separator is unnecessary:
      {prog} SETL [state ...]

    Use keyword "all" for all stages:
      {prog} all [state ...]

    Available States
    ----------------
    {allstates}""")

    usage: ClassVar = '{prog} [OPTIONS] <stages> [state ...]'

    @classmethod
    def parser_fmtargs(cls, parser):
        return super().parser_fmtargs(parser)|dict(
            allstates=' '.join(StatesOptTa.validate_python([])))

    @classmethod
    def add_arguments(cls, parser):
        arg = parser.add_argument
        arg('stages',
            metavar='<stages>',
            help='Stage name(s) (various formats) or "all"')
        arg('states',
            nargs='*',
            metavar='state',
            help=(
                'Optionally specify states as additional arguments. '
                'If not specified, include all states. To exclude a '
                'state, prefix with ^'))
        arg('--clean', '-c',
            action='store_true',
            help='Clean each stage before running')
        arg('--incremental', '-i',
            action='store_true',
            help=(
                'If a stage indicates no change after running, '
                'skip subsequent stages for the state'))
        arg('--concurrent', '-t',
            action='store_true',
            help=(
                'Use multiple async workers when applicable. '
                'The load stage is always synchronized with one worker'))
        arg('--nofail', '-n',
            action='store_false',
            dest='fail',
            help=(
                'Do not fail on error. Instead, log an exception, '
                'and skip subsequent stages for the state'))
        arg('--clean-only', '-x',
            action='store_true',
            help='Only clean, do not run')
        arg('--stat-only', '-s',
            action='store_true',
            help='Only show stats, do not run')
        arg('--search-dbname', '-d',
            metavar='<db>',
            help=f'Alternate mongo search db name')
        arg('--etl-dbname', '-b',
            metavar='<db>',
            help=f'Alternate mongo etl db name')
        arg('--max-workers', '-w',
            type=int,
            metavar='<n>',
            default=settings.ETL_DEFAULT_WORKERS,
            help=(
                'Max workers, applicable only when --concurrent is specified, '
                f'default ETL_DEFAULT_WORKERS ({settings.ETL_DEFAULT_WORKERS})'))
        arg('--max-threads', '-T',
            type=int,
            metavar='<n>',
            default=settings.ETL_DEFAULT_THREADS,
            help=(
                'Max threads, applicable only when --concurrent is specified, '
                f'default ETL_DEFAULT_THREADS ({settings.ETL_DEFAULT_THREADS})'))
        arg('--selenium-max-procs', '-E',
            type=int,
            metavar='<n>',
            default=settings.SELENIUM_MAX_PROCS,
            help=(
                'Max number of concurrent web drivers if applicable, '
                f'default SELENIUM_MAX_PROCS ({settings.SELENIUM_MAX_PROCS})'))
        arg('--rollback',
            action='store_true',
            help='Rollback SQL transaction on load stage')
        arg('--idfile',
            type=Path,
            metavar='<file>',
            help='Write the pipeline log ID to the given file')
        super().add_arguments(parser)

    def setup(self):
        super().setup()
        from ..pipeline import PipelineRunner
        runneropts = self.opts.model_dump()
        self.idfile: Path|None = runneropts.pop('idfile')
        runneropts['context'] = {
            settings.ETL_MONGODB_DBNAME_KEY: runneropts.pop('etl_dbname'),
            settings.SEARCH_MONGODB_DBNAME_KEY: runneropts.pop('search_dbname')}
        self.runner = PipelineRunner(**runneropts)

    async def run(self) -> None:
        if self.idfile:
            logger.info(f'Writing pipeline log ID to {self.idfile}')
            self.idfile.write_text(str(self.runner.log.id))
        await self.runner.run()
