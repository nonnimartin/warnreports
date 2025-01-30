from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Generic, Iterable, Iterator, TypeVar

import yaml
from sqlalchemy import (UUID, BigInteger, Column, DateTime, ForeignKey,
                        Integer, Select, String, Table, create_engine)
from sqlalchemy import delete as delete
from sqlalchemy import select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, aliased
from sqlalchemy.orm import joinedload as joinedload
from sqlalchemy.orm import (mapped_column, relationship, selectinload,
                            sessionmaker)
from sqlalchemy.sql import func

from . import settings, utils
from .models import (DM, ArtifactData, ArtifactDetail, CompanyDetail,
                     NaicsData, NaicsDetail, ReportData, StateDetail)
from .ref import normls

__all__ = [
    'Artifact',
    'Company',
    'Naics',
    'Report',
    'ReportMod',
    'SessionLocal',
    'StateStat']

RT = TypeVar('RT')
type ReportRowType = tuple[Report, Report, Naics|None, Artifact|None]
type StateStatRowType = tuple[StateStat]
type CompanyRowType = tuple[Company, Report, Naics|None]
type NaicsRowType = tuple[Naics, Report|None, Company|None]
type ArtifactRowType = tuple[Artifact, Report|None]
DEFAULT_YIELD_PER = 1000
logger = utils.get_logger('orm')
engine = create_engine(settings.DB_URL, echo=settings.QUERY_LOGGING)
SessionLocal = sessionmaker(autocommit=False, autoflush=True, bind=engine)

class Base(DeclarativeBase):

    def __init_subclass__(cls, **kw) -> None:
        if not cls.__dict__.get('__abstract__'):
            cls.__tablename__ = cls.__name__.lower()
            cls.__abstract__ = False
        super().__init_subclass__(**kw)

class MapReduceBase(Base, Generic[DM, RT]):
    __abstract__ = True
    data_model: ClassVar[type[DM]]

    @classmethod
    def map_reduce(cls, it: Iterable[RT]) -> Iterator[DM]:
        inst: DM|None = None
        for row in it:
            if inst is None or not cls.reduce_equals(inst, row):
                if inst is not None:
                    cls.reduce_finish(inst, memo)
                    yield inst
                memo = defaultdict(set)
                inst = cls.reduce_init(row, memo)
            cls.reduce_row(inst, row, memo)
        if inst is not None:
            cls.reduce_finish(inst, memo)
            yield inst

    @classmethod
    def map_reduce_exec(cls, session: Session, *filters, lazy: bool|int = True) -> Iterator[DM]:
        it = session.execute(cls.reduce_select(*filters, lazy=lazy))
        if not lazy:
            it = it.unique()
        return cls.map_reduce(it)

    @classmethod
    def reduce_select(cls, *filters, lazy: bool|int = True) -> Select[RT]:
        stmt = select(cls).where(*filters)
        stmt = lazify(stmt, lazy)
        return stmt

    @classmethod
    def reduce_init(cls, row: RT, memo: dict[str, set]) -> DM:
        'Create a new DataModel instance from the first result row'
        return cls.data_model.model_validate(row[0])

    @classmethod
    def reduce_row(cls, inst: DM, row: RT, memo: dict[str, set]) -> None:
        'Map a result row into a DataModel instance'
        pass

    @classmethod
    def reduce_finish(cls, inst: DM, memo: dict[str, set]) -> None:
        'Modify a fully-mapped DataModel instance'
        pass

    @classmethod
    def reduce_equals(cls, inst: DM, row: RT) -> bool:
        'Whether a result row represents the instance (individuation)'
        return inst.id == row[0].id

    def __init_subclass__(cls, **kw) -> None:
        cls.data_model = cls.__orig_bases__[0].__args__[0]
        super().__init_subclass__(**kw)

NaicsReport = Table(
    'naicsreport',
    Base.metadata,
    Column('naics_id', ForeignKey('naics.id', ondelete='CASCADE'), primary_key=True),
    Column('report_id', ForeignKey('report.id', ondelete='CASCADE'), primary_key=True))

ArtifactReport = Table(
    'artifactreport',
    Base.metadata,
    Column('artifact_id', ForeignKey('artifact.id', ondelete='CASCADE'), primary_key=True),
    Column('report_id', ForeignKey('report.id', ondelete='CASCADE'), primary_key=True))

nowopts = dict(server_default=func.now(), default=utils.now)

class Report(MapReduceBase[ReportData, ReportRowType]):
    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    company: Mapped[str] = mapped_column(String(512), index=True)
    company_norm: Mapped[str] = mapped_column(String(512), index=True)
    reported: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(2), index=True)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), **nowopts)
    location: Mapped[str|None] = mapped_column(String(255), nullable=True)
    starting: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    employees: Mapped[int] = mapped_column(Integer(), nullable=True)
    action: Mapped[str|None] = mapped_column(String(64), nullable=True)
    url: Mapped[str|None] = mapped_column(String(2083), nullable=True)
    naics: Mapped[list[Naics]] = relationship(secondary=NaicsReport, back_populates='reports')
    artifacts: Mapped[list[Artifact]] = relationship(secondary=ArtifactReport, back_populates='reports')

    @classmethod
    def reduce_select(cls, *filters, lazy: bool|int = True):
        Report2 = aliased(cls)
        stmt = (
            select(cls, Report2, Naics, Artifact)
            .join(Report2, cls.company_norm == Report2.company_norm)
            .join(Report2.naics, isouter=True)
            .join(cls.artifacts, isouter=True)
            .where(*filters)
            .order_by(cls.id, Naics.code, Artifact.id))
        stmt = lazify(stmt, lazy, (Report2.naics, cls.artifacts))
        return stmt

    @classmethod
    def reduce_init(cls, row, memo):
        inst = super().reduce_init(row, memo)
        memo['naics'].update(naics.id for naics in inst.naics)
        memo['artifacts'].update(artifact.id for artifact in inst.artifacts)
        inst.company_id = uuid.uuid5(Company.NS, row[0].company_norm)
        return inst

    @classmethod
    def reduce_row(cls, inst, row, memo):
        naics, artifact = row[2:]
        if naics and naics.id not in memo['naics']:
            inst.naics.append(NaicsData.model_validate(naics))
            memo['naics'].add(naics.id)
            for anc in naics.ancs:
                if anc.id not in memo['naics']:
                    inst.naics.append(NaicsData.model_validate(anc))
                    memo['naics'].add(anc.id)
        if artifact and artifact.id not in memo['artifacts']:
            inst.artifacts.append(ArtifactData.model_validate(artifact))
            memo['artifacts'].add(artifact.id)

    @classmethod
    def reduce_finish(cls, inst, memo):
        inst.naics.sort(key=lambda x: str(x.id))

class StateStat(MapReduceBase[StateDetail, StateStatRowType]):
    id: Mapped[str] = mapped_column(String(2), primary_key=True)
    last_reported: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    reports_count: Mapped[int] = mapped_column(Integer(), default=0)

    def self_update(self, session: Session):
        cond = Report.state == self.id
        stmt = select(func.count('*')).where(cond)
        self.reports_count = session.execute(stmt).scalar_one()
        stmt = select(func.max(Report.reported)).where(cond)
        latest = session.execute(stmt).scalar_one_or_none()
        if latest:
            self.last_reported = latest

class Company(MapReduceBase[CompanyDetail, CompanyRowType]):
    NS = uuid.uuid5(settings.NAMESPACE, 'Company')
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(512), unique=True)
    name_norm: Mapped[str] = mapped_column(String(512), index=True)
    name_canon: Mapped[str] = mapped_column(String(512), index=True)

    @classmethod
    def reduce_select(cls, *filters, lazy: bool|int = True):
        stmt = (
            select(cls, Report, Naics)
            .join(Report, Report.company_norm == cls.name_norm)
            .join(Report.naics, isouter=True)
            .where(*filters)
            .order_by(cls.name_norm, cls.name))
        stmt = lazify(stmt, lazy)
        return stmt

    @classmethod
    def reduce_init(cls, row, memo):
        inst = super().reduce_init(row, memo)
        company, report = row[:2]
        inst.id = uuid.uuid5(cls.NS, company.name_norm)
        inst.last_reported = report.reported
        return inst

    @classmethod
    def reduce_equals(cls, inst, row):
        return row[0].name_norm == normls.company_name_norm(inst.name)

    @classmethod
    def reduce_row(cls, inst, row, memo):
        company, report, naics = row
        memo['canon'].add(company.name_canon)
        for alias in company.name_canon, company.name:
            if alias not in memo['aliases']:
                inst.aliases.append(alias)
                memo['aliases'].add(alias)
        if report.id not in memo['reports']:
            inst.reports_count += 1
            if report.employees:
                inst.employees_sum += report.employees
            inst.last_reported = max(inst.last_reported, report.reported)
            memo['reports'].add(report.id)
            if report.state not in memo['states']:
                inst.states.append(report.state)
                memo['states'].add(report.state)
        if naics and naics.id not in memo['naics']:
            inst.naics.append(NaicsData.model_validate(naics))
            memo['naics'].add(naics.id)
            for anc in naics.ancs:
                if anc.id not in memo['naics']:
                    inst.naics.append(NaicsData.model_validate(anc))
                    memo['naics'].add(anc.id)

    @classmethod
    def reduce_finish(cls, inst, memo):
        inst.name = min(map(normls.company_name_sort, memo['canon']))[-1]
        inst.aliases.sort(key=lambda x: (x.lower(), x))
        inst.naics.sort(key=lambda x: str(x.id))
        inst.states.sort()
        inst.states_count = len(inst.states)

class Naics(MapReduceBase[NaicsDetail, NaicsRowType]):
    id: Mapped[int] = mapped_column(Integer(), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    left: Mapped[int] = mapped_column(Integer(), unique=True)
    right: Mapped[int] = mapped_column(Integer(), unique=True)
    depth: Mapped[int] = mapped_column(Integer())
    parent: Mapped[int|None] = mapped_column(Integer(), nullable=True)
    reports: Mapped[list[Report]] = relationship(secondary=NaicsReport, back_populates='naics')
    ancs: Mapped[list[Naics]] = relationship(
        'Naics',
        primaryjoin='and_(Naics.left > remote(foreign(Naics.left)), Naics.right < remote(foreign(Naics.right)))',
        viewonly=True,
        order_by=id.desc())

    @property
    def root(self) -> int:
        return int(str(self.id)[:2])

    @classmethod
    def reduce_select(cls, *filters, lazy: bool = True):
        stmt = (
            select(cls, Report, Company)
            .join(cls.reports, isouter=True)
            .join(
                Company,
                Report.company_norm == Company.name_canon,
                isouter=True)
            .where(*filters)
            .order_by(cls.id, Report.company_norm, Company.name_norm))
        stmt = lazify(stmt, lazy)
        return stmt

    @classmethod
    def reduce_row(cls, inst, row, memo):
        report, company = row[1:]
        if report and report.id not in memo['reports']:
            inst.reports_count += 1
            if report.employees:
                inst.employees_sum += report.employees
            memo['reports'].add(report.id)
            if report.company_norm not in memo['companies']:
                inst.companies_count += 1
                memo['companies'].add(report.company_norm)
        if company and company.name_norm not in memo['companies']:
            inst.companies_count += 1
            memo['companies'].add(company.name_norm)

class Artifact(MapReduceBase[ArtifactDetail, ArtifactRowType]):
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(2083), unique=True)
    url: Mapped[str] = mapped_column(String(2083))
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), **nowopts)
    modified: Mapped[datetime] = mapped_column(DateTime(timezone=True), **nowopts)
    media_type: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(BigInteger())
    sha1: Mapped[str] = mapped_column(String(40))
    reports: Mapped[list[Report]] = relationship(secondary=ArtifactReport, back_populates='artifacts')

    @property
    def name(self):
        return Path(self.path).name

    @classmethod
    def reduce_select(cls, *filters, lazy: bool|int = True):
        stmt = (
            select(cls, Report)
            .join(cls.reports, isouter=True)
            .where(*filters)
            .order_by(cls.id))
        stmt = lazify(stmt, lazy)
        return stmt

    @classmethod
    def reduce_row(cls, inst, row, memo):
        if (report := row[1]) and report.id not in memo['reports']:
            inst.reports_count += 1
            memo['reports'].add(report.id)

    def self_update(self) -> bool:
        file = Path(settings.ARTIFACTS_DIR, self.path)
        with file.open('rb') as f:
            digest = hashlib.file_digest(f, 'sha1')
        stat = file.stat()
        data = dict(
            size=stat.st_size,
            modified=datetime.fromtimestamp(stat.st_mtime),
            media_type=utils.get_mimetype(file),
            sha1=digest.hexdigest())
        change = False
        for field, value in data.items():
            if getattr(self, field) != value:
                setattr(self, field, value)
                change = True
        return change

class ReportMod(Base):
    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    ns: Mapped[uuid.UUID] = mapped_column(UUID(), index=True)
    first_scraped: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)

def lazify(stmt: Select[RT], lazy: bool|int = True, joins: Iterable|None = None) -> Select[RT]:
    if lazy:
        joinfunc = selectinload
        yield_per = lazy if lazy > 1 else DEFAULT_YIELD_PER
        stmt = stmt.execution_options(yield_per=yield_per)
    else:
        joinfunc = joinedload
    if joins:
        for column in joins:
            stmt = stmt.options(joinfunc(column))
    return stmt

def load_naics() -> None:
    'Load NAICS data'
    with SessionLocal() as session:
        exists = bool(
            session
            .execute(select(Naics.id).limit(1))
            .scalar_one_or_none())
        if exists:
            logger.info(f'NAICS already loaded')
            return
        logger.info(f'Loading NAICS')
        import requests
        rep = requests.get(settings.NAICS_DOWNLOAD)
        rep.raise_for_status()
        session.add_all(
            Naics(
                id=entry['code'],
                code=entry['code_raw'],
                title=entry['title'],
                left=entry['left'],
                right=entry['right'],
                depth=entry['depth'],
                parent=entry['parent'])
            for entry in rep.json())
        session.commit()

def dump_csv(table: Table, f: io.TextIOWrapper, session: Session) -> None:
    stmt = table.select().order_by(*table.primary_key.columns)
    writer = csv.writer(f)
    writer.writerow(c.name for c in table.columns)
    writer.writerows(session.execute(lazify(stmt)).tuples())

def dump_update(table: Table, file: Path|None = None) -> None:
    'Dump table CSV'
    if not file:
        file = settings.BUILD_DIR/'dump'/f'{table.name}.csv'
    if file.exists():
        with file.open('rb') as f:
            hash_old = hashlib.file_digest(f, 'sha1')
    else:
        hash_old = None
        file.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(f'{file}.tmp')
    logger.info(f'Dumping table {table.name}')
    with SessionLocal() as session:
        with tmp.open('w') as f:
            dump_csv(table, f, session)
    with tmp.open('rb') as f:
        hash_new = hashlib.file_digest(f, 'sha1')
    if hash_old and hash_old.digest() == hash_new.digest():
        logger.info(f'No change')
        tmp.unlink()
    else:
        logger.info(f'Writing {file}')
        tmp.rename(file)

class NaicsCommand(utils.FuncCommand(load_naics)):
    pass

class DumpCommand(utils.FuncCommand(dump_update)):

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument('table', type=lambda x: Base.metadata.tables[x.lower()])
        parser.add_argument('file', nargs='?', type=Path)

class MroneCommand(utils.BaseCommand):
    'Run map-reduce for a single object and print json'

    models = dict(
        report=Report,
        artifact=Artifact,
        naics=Naics,
        company=Company,
        state=StateStat)

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument('--model', '-m', choices=cls.models, default='report', help='Model name, default report')
        parser.add_argument('--yaml', action='store_true', help='Output yaml')
        parser.add_argument('id', help='The object primary key. For company, this is the name')

    def setup(self, opts):
        super().setup(opts)
        self.model: type[MapReduceBase] = self.models[opts.model]
        self.filterkw = {}
        if self.model is Company:
            field = 'name_norm'
            value = normls.company_name_norm(opts.id)
        else:
            field = 'id'
            value = opts.id
        self.filterkw = {field: value}
        self.filter = getattr(self.model, field) == value

    def run(self):
        with SessionLocal() as session:
            res = list(self.model.map_reduce_exec(session, self.filter))
        if not res:
            raise ValueError(f'Not found: {self.filterkw}')
        obj, = res
        obj = json.loads(obj.model_dump_json())
        self.printobj(obj)

    def printobj(self, obj):
        if self.opts.yaml:
            text = yaml.safe_dump(obj, sort_keys=False)
        else:
            text = json.dumps(obj, indent=2)
        print(text)

class Command(utils.BaseCommand):
    'ORM/SQL commands'
    commands = dict(dump=DumpCommand, naics=NaicsCommand, mrone=MroneCommand)


if __name__ == '__main__':
    Command.main()
