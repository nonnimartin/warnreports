from __future__ import annotations

import logging
from collections import defaultdict, deque
from pathlib import Path
from textwrap import dedent
from typing import Any, ClassVar

from pydantic import Field

from .. import Stage, settings
from ..models import PipelineBatchOpts, PipelineOpts
from .base import AppCommand, AppCommandOpts
from .validators import ALLSTATES, StagesOpt, StatesOpt

logger = logging.getLogger(__name__)

class PipelineCommandOpts(AppCommandOpts, PipelineBatchOpts, PipelineOpts):
    stages: StagesOpt
    states: StatesOpt
    etl_dbname: str|None = Field(
        default=None,
        exclude=True,
        description=f'Alternate mongo etl db name')
    search_dbname: str|None = Field(
        default=None,
        exclude=True,
        description=f'Alternate mongo search db name')
    idfile: Path|None = Field(
        default=None,
        exclude=True,
        description='Write the pipeline log ID to the given file')
    normfile: Path|None = Field(
        default=None,
        exclude=True,
        description='Write company name normalizations to the given file')

class Command(AppCommand[PipelineCommandOpts]):
    options_class: ClassVar = PipelineCommandOpts
    usage: ClassVar = '{prog} [OPTIONS] <stages> [state ...]'
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

    Available stages: {allstages}

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

    @classmethod
    def parser_fmtargs(cls, parser) -> dict[str, Any]:
        return super().parser_fmtargs(parser)|dict(
            allstages=', '.join(Stage),
            allstates=' '.join(ALLSTATES))

    @classmethod
    def add_arguments(cls, parser) -> None:
        arg = parser.add_argument
        arg('stages', metavar='<stages>')
        arg('states', nargs='*', metavar='state')
        arg('--clean', '-c')
        arg('--incremental', '-i')
        arg('--concurrent', '-t')
        arg('--nofail', '-n')
        arg('--clean-only', '-x')
        arg('--stat-only', '-s')
        arg('--search-dbname', '-d', metavar='<db>')
        arg('--etl-dbname', '-b', metavar='<db>')
        arg('--max-workers', '-w', metavar='<n>')
        arg('--max-threads', '-T', metavar='<n>')
        arg('--selenium-max-procs', '-E', metavar='<n>')
        arg('--rollback')
        arg('--idfile', metavar='<file>')
        arg('--normfile', metavar='<file>')
        super().add_arguments(parser)

    def setup(self) -> None:
        super().setup()
        if self.opts.normfile:
            self.opts.normlog = deque()
        from ..pipeline import PipelineRunner
        self.runner = PipelineRunner(
            **self.opts.model_dump(),
            context={
                settings.ETL_MONGODB_DBNAME_KEY: self.opts.etl_dbname,
                settings.SEARCH_MONGODB_DBNAME_KEY: self.opts.search_dbname})
        self.runner.pipeline_opts.normlog = self.opts.normlog

    async def run(self) -> None:
        if self.opts.idfile:
            logger.info(f'Writing pipeline log ID to {self.opts.idfile}')
            self.opts.idfile.write_text(str(self.runner.log.id))
        await self.runner.run()
        if self.opts.normfile:
            self.write_normlog()

    def write_normlog(self) -> None:
        file = self.opts.normfile
        normlog = self.opts.normlog
        logger.info(f'Writing {len(normlog)} norms to {file}')
        norms: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for canon, raw in normlog:
            norms[canon][raw] += 1
        data = {
            canon: dict(
                sorted(
                    norms[canon].items(),
                    key=lambda x: x[1],
                    reverse=True))
            for canon in sorted(norms)}
        import yaml
        with file.open('w') as fp:
            yaml.safe_dump(data, fp, sort_keys=False)
