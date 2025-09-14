from __future__ import annotations

import glob
import json
import logging
import uuid
from pathlib import Path
from textwrap import dedent
from typing import Any, ClassVar

import yaml

from .. import orm, settings
from ..models import DataModel
from ..orm import *
from ..orm import Base, MapReduceBase, dump_update, load_naics, select
from ..tools import files
from .base import AppCommand, BaseCommand, BaseCommandOpts, FuncCommand
from .validators import StatesOpt

logger = logging.getLogger(__name__)

class NaicsCommand(FuncCommand(load_naics, AppCommand)):
    pass

class DumpCommand(FuncCommand(dump_update, AppCommand)):

    @classmethod
    def add_arguments(cls, parser):
        arg = parser.add_argument
        arg(
            'table',
            metavar='table',
            choices=Base.metadata.tables,
            help=f'The table ({'|'.join(sorted(Base.metadata.tables))})')
        arg(
            'file',
            nargs='?',
            type=Path,
            help=('The output file, default BUILD_DIR/dump/[table].csv'))
        super().add_arguments(parser)

class MroneCommand(AppCommand[BaseCommandOpts]):
    description = dedent("""
    Run map-reduce for a single object and print the resulting data model object

    Examples
    --------

    Report
    $ {prog} 9445518b-3192-5eb2-b5ce-710c18f24368

    Company
    $ {prog} -m company 3224e161-3705-5f5e-9661-abcfe0e3f24e
    $ {prog} -m company Safeway
    $ {prog} -m company 'Safeway, Inc.'

    State
    $ {prog} -m state CA

    Naics
    $ {prog} -m naics 44511

    Artifact
    $ {prog} -m artifact 0ab65afb-2d9f-5754-b1ad-e03d99cac511
    $ {prog} -m artifact ca/warn_report1.xlsx
    ------------------------------------------------------------
    """)

    @classmethod
    def modelopt(cls, value: str) -> type[MapReduceBase]:
        if value.lower() == 'state':
            value = 'StateStat'
        for model in orm.MRCLASSES:
            if model.__name__.lower() == value.lower():
                return model
        raise ValueError

    @classmethod
    def add_arguments(cls, parser):
        arg = parser.add_argument
        arg(
            '--model', '-m',
            type=cls.modelopt,
            default=Report,
            help=(f'The ORM model name, default Report '
                  f'({'|'.join(x.__name__ for x in orm.MRCLASSES)})'))
        arg(
            '--yaml',
            action='store_true',
            help='Output yaml')
        arg(
            'id',
            help='The object primary key (see examples)')
        super().add_arguments(parser)

    def setup(self):
        super().setup()
        self.model: type[MapReduceBase] = self.opts.model
        if self.model is Company:
            field = 'name_norm_id'
        else:
            field = 'id'
        value = self.opts.id
        if self.model is Company:
            try:
                value = uuid.UUID(value)
            except ValueError:
                from ..ref.normls import company_name_norm
                value = uuid.uuid5(Company.NS, company_name_norm(value))
        elif self.model is Artifact and '/' in value:
            value = Artifact.path_to_id(value)
        elif self.model is StateStat:
            value = str(value).upper()
        elif self.model is Naics:
            value = int(value)
        else:
            value = uuid.UUID(value)
        self.filterkw = {field: value}
        self.filter = getattr(self.model, field) == value

    def run(self):
        with SessionLocal() as session:
            res = tuple(self.model.map_reduce_exec(session, self.filter, lazy=False))
        if not res:
            raise ValueError(f'Not found: {self.filterkw}')
        obj, = res
        objdict = self.dumpobj(obj)
        text = self.dictstr(objdict)
        print(text)

    def dumpobj(self, obj: DataModel) -> dict[str, Any]:
        return obj.model_dump(mode='json')

    def dictstr(self, objdict: dict[str, Any]) -> str:
        if self.opts.yaml:
            return yaml.safe_dump(objdict, sort_keys=False)
        return json.dumps(objdict, indent=2)

class ArtifactsCommandOpts(BaseCommandOpts):
    change: bool = True
    dir: Path = settings.ARTIFACTS_DIR
    states: StatesOpt

class ArtifactsCommand(BaseCommand):
    'Artifacts maintenance'

    class Base(AppCommand[ArtifactsCommandOpts]):
        options_class: ClassVar = ArtifactsCommandOpts

        @classmethod
        def add_arguments(cls, parser):
            arg = parser.add_argument
            arg(
                '--check-only', '-c',
                action='store_false',
                dest='change',
                help='Check only, do not make changes')
            arg(
                '--dir', '-d',
                type=Path,
                default=settings.ARTIFACTS_DIR,
                help=f'Artifacts base dir, default is settings.ARTIFACTS_DIR')
            arg(
                'states',
                nargs='*',
                metavar='state',
                help='Restrict to a specific states')
            super().add_arguments(parser)

    class Prune(Base):
        'Delete orphan artifacts from file system'

        def run(self) -> None:
            with SessionLocal() as session:
                for state in self.opts.states:
                    logger.debug(f'Checking {state=}')
                    it = glob.iglob(
                        f'{state.lower()}/**/*.*',
                        root_dir=self.opts.dir,
                        recursive=True)
                    for path in it:
                        self.checkpath(path, session)

        def checkpath(self, path: str, session: orm.Session) -> None:
            logger.debug(f'Checking {path=}')
            file = self.opts.dir/path
            if path.endswith('.sha1'):
                logger.info(f'Cruft {path=}')
                if self.opts.change:
                    file.unlink()
                return
            id = Artifact.path_to_id(path)
            try:
                session.get_one(Artifact, id)
            except NoResultFound:
                logger.info(f'Orphan {path=} {id=}')
                if self.opts.change:
                    file.unlink()
                    files.digestfile(file).unlink(missing_ok=True)
            else:
                logger.debug(f'Found {path=} {id=}')

    class Update(Base):
        'Update artifacts in DB from files'

        def run(self):
            with SessionLocal() as session:
                for state in self.opts.states:
                    logger.debug(f'Updating {state=}')
                    stmt = (select(Artifact)
                        .where(Artifact.path.startswith(f'{state.lower()}/')))
                    for art in session.scalars(stmt):
                        self.checkart(art, session)
                if self.opts.change:
                    session.commit()
                else:
                    session.rollback()

        def checkart(self, art: Artifact, session: orm.Session) -> None:
            file = self.opts.dir/art.path
            if file.exists():
                logger.debug(f'Found path={art.path} id={art.id}')
                if art.self_update(root=self.opts.dir):
                    logger.info(f'Updated path={art.path} id={art.id}')
                    session.add(art)
            else:
                logger.warning(f'Missing path={art.path} id={art.id}')

    commands = dict(update=Update, prune=Prune)

class Command(BaseCommand):
    'ORM/SQL commands'
    commands = dict(
        artifacts=ArtifactsCommand,
        mrone=MroneCommand,
        dump=DumpCommand,
        naics=NaicsCommand)
