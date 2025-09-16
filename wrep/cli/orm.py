from __future__ import annotations

import enum
import glob
import json
import logging
import uuid
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self

import yaml
from pydantic import Field, model_validator

from .. import settings
from ..models import ValidStateCode
from .base import AppCommand, AppCommandOpts
from .validators import StatesOpt

if TYPE_CHECKING:
    from .. import orm
    from ..models import DataModel

logger = logging.getLogger(__name__)

class OrmTable(enum.StrEnum):
    artifact = 'artifact'
    artifactreport = 'artifactreport'
    company = 'company'
    naics = 'naics'
    naicsreport = 'naicsreport'
    report = 'report'
    reportmod = 'reportmod'
    statestat = 'statestat'

class MrModelName(enum.StrEnum):
    report = 'Report'
    artifact = 'Artifact'
    company = 'Company'
    state = 'StateStat'
    naics = 'Naics'

    @classmethod
    def _missing_(cls, value) -> Self:
        return cls[str(value).lower()]

    def orm_model(self) -> type[orm.MapReduceBase]:
        from ..orm import MapReduceBase
        for cls in MapReduceBase.__subclasses__():
            if not cls.__abstract__ and cls.__name__ == self.value:
                return cls
        raise ValueError(self.value)

class DumpOpts(AppCommandOpts):
    table: OrmTable = Field(description=f'The table ({'|'.join(OrmTable)})')
    file: Path|None = Field(description='The output file, default BUILD_DIR/dump/[table].csv')

class NaicsOpts(AppCommandOpts):
    ...

class ArtifactsOpts(AppCommandOpts):
    dryrun: bool = Field(False, description='Dry run only')
    dir: Path = Field(
        default=settings.ARTIFACTS_DIR,
        description=f'Artifacts base dir, default ARTIFACTS_DIR')
    states: StatesOpt

class MroneOpts(AppCommandOpts):
    id: str|int|uuid.UUID = Field(description='The object primary key (see examples)')
    model: MrModelName = Field(
        default=MrModelName.report,
        description=f'The ORM model name, default Report')
    output: Literal['json', 'yaml'] = Field('json', description='Output, default json')

    @property
    def field(self) -> Literal['name_norm_id', 'id']:
        if self.model == MrModelName.company:
            return 'name_norm_id'
        return 'id'

    @model_validator(mode='after')
    def resolveid(self) -> Self:
        value = self.id
        model = self.model
        if model is model.company:
            try:
                value = uuid.UUID(value)
            except ValueError:
                from ..ref.normls import company_name_norm
                value = uuid.uuid5(model.orm_model().NS, company_name_norm(value))
        elif model is model.artifact and '/' in value:
            value = model.orm_model().path_to_id(value)
        elif model is model.state:
            value = ValidStateCode(value)
        elif model is model.naics:
            value = int(value)
        else:
            value = uuid.UUID(value)
        self.id = value
        return self

class NaicsCommand(AppCommand[NaicsOpts]):
    'Load NAICS data'
    options_class: ClassVar = NaicsOpts

    def run(self):
        from ..orm import load_naics
        load_naics(**self.opts.model_dump())

class DumpCommand(AppCommand[DumpOpts]):
    'Dump table CSV'
    options_class: ClassVar = DumpOpts

    @classmethod
    def add_arguments(cls, parser):
        arg = parser.add_argument
        arg('table', metavar='table', choices=(...,))
        arg('file', nargs='?')
        super().add_arguments(parser)

    def run(self):
        from ..orm import dump_update
        dump_update(**self.opts.model_dump())

class MroneCommand(AppCommand[MroneOpts]):
    options_class: ClassVar = MroneOpts
    description: ClassVar = dedent("""
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
    def add_arguments(cls, parser):
        arg = parser.add_argument
        arg('--model', '-m', default=...,)
        arg('--output', '-o', default=..., choices=(...,))
        arg('id')
        super().add_arguments(parser)

    def setup(self):
        super().setup()
        self.model = self.opts.model.orm_model()
        self.filterkw = {self.opts.field: self.opts.id}
        self.filter = getattr(self.model, self.opts.field) == self.opts.id

    def run(self):
        from .. import orm
        with orm.SessionLocal() as session:
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
        if self.opts.output == 'yaml':
            return yaml.safe_dump(objdict, sort_keys=False)
        return json.dumps(objdict, indent=2)

class ArtifactsBase(AppCommand[ArtifactsOpts]):
    options_class: ClassVar = ArtifactsOpts

    @classmethod
    def add_arguments(cls, parser):
        arg = parser.add_argument
        arg('--dryrun')
        arg('--dir', '-d', default=...)
        arg('states', nargs='*', metavar='state')
        super().add_arguments(parser)

class ArtifactsPrune(ArtifactsBase):
    'Delete orphan artifacts from file system'

    def run(self) -> None:
        from .. import orm
        with orm.SessionLocal() as session:
            for state in self.opts.states:
                logger.debug(f'Checking {state=}')
                it = glob.iglob(
                    f'{state.lower()}/**/*.*',
                    root_dir=self.opts.dir,
                    recursive=True)
                for path in it:
                    self.checkpath(path, session)

    def checkpath(self, path: str, session: orm.Session) -> None:
        from .. import orm
        from ..tools import files
        logger.debug(f'Checking {path=}')
        file = self.opts.dir/path
        if path.endswith('.sha1'):
            logger.info(f'Cruft {path=}')
            if not self.opts.dryrun:
                file.unlink()
            return
        id = orm.Artifact.path_to_id(path)
        try:
            session.get_one(orm.Artifact, id)
        except orm.NoResultFound:
            logger.info(f'Orphan {path=} {id=}')
            if not self.opts.dryrun:
                file.unlink()
                files.digestfile(file).unlink(missing_ok=True)
        else:
            logger.debug(f'Found {path=} {id=}')

class ArtifactsUpdate(ArtifactsBase):
    'Update artifacts in DB from files'

    def run(self):
        from .. import orm
        with orm.SessionLocal() as session:
            for state in self.opts.states:
                logger.debug(f'Updating {state=}')
                stmt = (orm.select(orm.Artifact)
                    .where(orm.Artifact.path.startswith(f'{state.lower()}/')))
                for art in session.scalars(stmt):
                    self.checkart(art, session)
            if not self.opts.dryrun:
                session.commit()
            else:
                session.rollback()

    def checkart(self, art: orm.Artifact, session: orm.Session) -> None:
        file = self.opts.dir/art.path
        if file.exists():
            logger.debug(f'Found path={art.path} id={art.id}')
            if art.self_update(root=self.opts.dir):
                logger.info(f'Updated path={art.path} id={art.id}')
                session.add(art)
        else:
            logger.warning(f'Missing path={art.path} id={art.id}')

commands = dict(
    _description='ORM/SQL commands',
    artifacts=dict(
        _description='Artifacts maintenance',
        update=ArtifactsUpdate,
        prune=ArtifactsPrune),
    mrone=MroneCommand,
    dump=DumpCommand,
    naics=NaicsCommand)
