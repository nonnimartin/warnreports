from __future__ import annotations

import glob
import json
import uuid
from pathlib import Path
from typing import Any

import yaml

from .. import settings, utils
from ..models import DataModel
from ..orm import *
from ..orm import Base, MapReduceBase, dump_update, load_naics, select
from .base import AppCommand, BaseCommand, FuncCommand

logger = utils.get_logger('orm')

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

class MroneCommand(AppCommand):
    description = """
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
    """
    mrclasses = [
        cls for cls in MapReduceBase.__subclasses__()
        if not cls.__abstract__]
    mrclasses.sort(key=lambda x: x.__name__)

    @classmethod
    def modelopt(cls, value: str) -> type[MapReduceBase]:
        if value.lower() == 'state':
            value = 'StateStat'
        for model in cls.mrclasses:
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
                  f'({'|'.join(x.__name__ for x in cls.mrclasses)})'))
        arg(
            '--yaml',
            action='store_true',
            help='Output yaml')
        arg(
            'id',
            help='The object primary key (see examples)')
        super().add_arguments(parser)

    def setup(self, opts):
        super().setup(opts)
        self.model: type[MapReduceBase] = opts.model
        if self.model is Company:
            field = 'name_norm_id'
        else:
            field = 'id'
        value = opts.id
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

class ArtifactsCommand(BaseCommand):
    'Artifacts maintenance'

    class Base(AppCommand):

        @classmethod
        def add_arguments(cls, parser):
            arg = parser.add_argument
            arg(
                '--check-only', '-c',
                action='store_false',
                dest='change',
                help='Check only, do not make changes')
            arg(
                'dir',
                nargs='?',
                type=Path,
                help=f'Alternate artifacts dir')
            super().add_arguments(parser)

        def setup(self, opts):
            super().setup(opts)
            self.root: Path = opts.dir or settings.ARTIFACTS_DIR

    class Prune(Base):
        'Delete orphan artifacts from file system'

        async def run(self):
            it = glob.iglob('**/*.*', root_dir=self.root, recursive=True)
            with SessionLocal() as session:
                for path in it:
                    file = self.root/path
                    if path.endswith('.sha1'):
                        logger.info(f'Cruft {path=}')
                        if self.opts.change:
                            file.unlink()
                        continue
                    id = Artifact.path_to_id(path)
                    try:
                        session.get(Artifact, id)
                    except NoResultFound:
                        logger.info(f'Orphan {path=} {id=}')
                        if self.opts.change:
                            file.unlink()
                            utils.digestfile(file).unlink(missing_ok=True)
                    else:
                        logger.debug(f'Found {path=} {id=}')

    class Update(Base):
        'Update artifacts in DB from files'

        async def run(self):
            stmt = select(Artifact)
            with SessionLocal() as session:
                for art in session.scalars(stmt):
                    file = self.root/art.path
                    if file.exists():
                        logger.debug(f'Found path={art.path} id={art.id}')
                        if art.self_update(root=self.root):
                            logger.info(f'Updated path={art.path} id={art.id}')
                            session.add(art)
                    else:
                        logger.warning(f'Missing path={art.path} id={art.id}')
                if self.opts.change:
                    session.commit()
                else:
                    session.rollback()

    commands = dict(update=Update, prune=Prune)

class Command(BaseCommand):
    'ORM/SQL commands'
    commands = dict(
        artifacts=ArtifactsCommand,
        mrone=MroneCommand,
        dump=DumpCommand,
        naics=NaicsCommand)
