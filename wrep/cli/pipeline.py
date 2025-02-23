from __future__ import annotations

from pathlib import Path

from .. import Stage, settings, utils
from ..translators import TranslationFactory
from .base import AppCommand

logger = utils.get_logger('pipeline')

class Command(AppCommand):
    description = """
    Run pipeline stages.
    
    Basic Examples
    --------------

    Run single stage for all states:
    $ {prog} scrape

    Run single stage for some states:
    $ {prog} extract CA NY

    Run all stages for some states:
    $ {prog} all FL OH

    Run all stages for all states:
    $ {prog} all

    Selecting Stages
    -----------------

    Available stages: """ + ', '.join(Stage) + """

    Specify multiple stages with a comma:
    $ {prog} scrape,extract [state ...]

    Using first letter with comma:
    $ {prog} s,e,t [state ...]

    With capital first letters, separator is unnecessary:
    $ {prog} SETL [state ...]

    Use keyword "all" for all stages:
    $ {prog} all [state ...]

    Available States
    ----------------
    """ + ' '.join(sorted(TranslationFactory.translators))

    usage = '{prog} [OPTIONS] <stages> [state ...]'

    @classmethod
    def add_arguments(cls, parser):
        arg = parser.add_argument
        arg('stages',
            metavar='<stages>',
            type=cls.stages_opt,
            help='Stage name(s) (various formats) or "all"')
        arg('states',
            nargs='*',
            metavar='state',
            help=(
                'Optionally specify states as additional arguments. '
                'If not specified, include all states'))
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
            default=None,
            help=f'Alternate mongo search db name')
        arg('--etl-dbname', '-b',
            default=None,
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
        arg('--eager', '-e',
            action='store_false',
            dest='lazy',
            help='Use eager loading of SQL result sets. Uses more memory')
        arg('--rollback',
            action='store_true',
            help='Rollback SQL transaction on load stage')
        arg('--idfile',
            default=None,
            type=Path,
            help='Write the pipeline log ID to the given file')
        super().add_arguments(parser)

    def setup(self, opts):
        super().setup(opts)
        from .. import search
        from ..backends import etl
        from ..pipeline import PipelineRunner
        opts.states = opts.states or sorted(TranslationFactory.translators)
        runner_opts = dict(vars(opts))
        self.idfile: Path|None = runner_opts.pop('idfile')
        runner_opts['context'] = {
            etl.client.dbname_key: runner_opts.pop('etl_dbname'),
            search.client.dbname_key: runner_opts.pop('search_dbname')}
        self.runner = PipelineRunner(**runner_opts)

    async def run(self):
        if self.idfile:
            logger.info(f'Writing pipeline log ID to {self.idfile}')
            self.idfile.write_text(str(self.runner.log.id))
        await self.runner.run()

    @staticmethod
    def stages_opt(value: str) -> list[Stage]:
        if value == 'all':
            return list(Stage)
        value = value.replace(',', ' ')
        for stage in Stage:
            value = value.replace(stage[0].upper(), f' {stage.value} ')
        trans = {stage[0]: stage for stage in Stage}
        return [Stage(trans.get(value, value)) for value in value.split()]
