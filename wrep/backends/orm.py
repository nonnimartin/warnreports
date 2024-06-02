from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Generic, Iterable, Iterator, TypeVar

from sqlalchemy import (UUID, BigInteger, Column, DateTime, ForeignKey,
                        Integer, Select, String, Table, create_engine)
from sqlalchemy import delete as delete
from sqlalchemy import select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, aliased
from sqlalchemy.orm import joinedload as joinedload
from sqlalchemy.orm import (mapped_column, relationship, selectinload,
                            sessionmaker)
from sqlalchemy.sql import func

from .. import settings, utils
from ..models import (DM, ArtifactData, ArtifactDetail, CompanyDetail,
                      NaicsData, NaicsDetail, ReportData, StateDetail)
from ..ref import normls

__all__ = [
    'Artifact',
    'Company',
    'Naics',
    'Report',
    'SessionLocal',
    'StateStat']

RT = TypeVar('RT')
logger = utils.get_logger('backends.orm')
engine = create_engine(settings.DB_URL, echo=settings.QUERY_LOGGING)
SessionLocal = sessionmaker(autocommit=False, autoflush=True, bind=engine)
DEFAULT_YIELD_PER = 1000

class Base(DeclarativeBase, Generic[DM, RT]):

    data_model: type[DM]

    @classmethod
    def map_reduce_exec(cls, session: Session, *filters, lazy: bool|int = True) -> Iterator[DM]:
        it = session.execute(cls.reduce_select(*filters, lazy=lazy))
        if not lazy:
            it = it.unique()
        return cls.map_reduce(it)

    @classmethod
    def reduce_select(cls, *filters, lazy: bool|int = True) -> Select[RT]:
        stmt = select(cls).where(*filters)
        if lazy:
            yield_per = lazy if lazy > 1 else DEFAULT_YIELD_PER
            stmt = stmt.execution_options(yield_per=yield_per)
        return stmt

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
    def reduce_init(cls, row: RT, memo: dict[str, set]) -> DM:
        return cls.data_model.model_validate(row[0])

    @classmethod
    def reduce_equals(cls, inst: DM, row: RT) -> bool:
        return inst.id == row[0].id

    @classmethod
    def reduce_row(cls, inst: DM, row: RT, memo: dict[str, set]) -> None:
        pass

    @classmethod
    def reduce_finish(cls, inst: DM, memo: dict[str, set]) -> None:
        pass

    def __init_subclass__(cls, **kw) -> None:
        cls.__tablename__ = cls.__name__.lower()
        cls.data_model = cls.__orig_bases__[0].__args__[0]
        super().__init_subclass__(**kw)

NaicsReport = Table(
    'naicsreport',
    Base.metadata,
    Column('naics_id', ForeignKey('naics.id'), primary_key=True),
    Column('report_id', ForeignKey('report.id'), primary_key=True))

ArtifactReport = Table(
    'artifactreport',
    Base.metadata,
    Column('artifact_id', ForeignKey('artifact.id'), primary_key=True),
    Column('report_id', ForeignKey('report.id'), primary_key=True))

nowopts = dict(server_default=func.now(), default=utils.now)

class Report(Base[ReportData, tuple['Report', 'Report', 'Naics|None', 'Artifact|None']]):
    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    company: Mapped[str] = mapped_column(String(512), index=True)
    company_norm: Mapped[str] = mapped_column(String(512), index=True)
    reported: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(2), index=True)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), **nowopts)
    location: Mapped[str|None] = mapped_column(String(255), nullable=True)
    starting : Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    employees: Mapped[int] = mapped_column(Integer(), nullable=True)
    action: Mapped[str|None] = mapped_column(String(64), nullable=True)
    url: Mapped[str|None] = mapped_column(String(2083), nullable=True)
    naics: Mapped[list[Naics]] = relationship(secondary=NaicsReport, back_populates='reports')
    artifacts: Mapped[list[Artifact]] = relationship(secondary=ArtifactReport, back_populates='reports')

    @classmethod
    def reduce_select(cls, *filters, lazy: bool|int = True):
        joinfunc = selectinload if lazy else joinedload
        stmt = (
            select(cls, Report2 := aliased(cls), Naics, Artifact)
            .join(Report2, cls.company_norm == Report2.company_norm)
            .join(Report2.naics, isouter=True)
            .join(cls.artifacts, isouter=True)
            .where(*filters)
            .order_by(cls.id, Naics.code, Artifact.id)
            .options(joinfunc(Report2.naics))
            .options(joinfunc(cls.artifacts)))
        if lazy:
            yield_per = lazy if lazy > 1 else DEFAULT_YIELD_PER
            stmt = stmt.execution_options(yield_per=yield_per)
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
        if artifact and artifact.id not in memo['artifacts']:
            inst.artifacts.append(ArtifactData.model_validate(artifact))
            memo['artifacts'].add(artifact.id)

    @classmethod
    def reduce_finish(cls, inst, memo):
        inst.naics.sort(key=lambda x: (x.code, x.id))

class StateStat(Base[StateDetail, tuple['StateStat']]):
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

class Company(Base[CompanyDetail, tuple['Company', Report, 'Naics|None']]):
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
        if lazy:
            yield_per = lazy if lazy > 1 else DEFAULT_YIELD_PER
            stmt = stmt.execution_options(yield_per=yield_per)
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

    @classmethod
    def reduce_finish(cls, inst, memo):
        inst.name = min(map(normls.company_name_sort, memo['canon']))[-1]
        inst.aliases.sort(key=lambda x: (x.lower(), x))
        inst.naics.sort(key=lambda x: (x.code, x.id))
        inst.states.sort()

class Naics(Base[NaicsDetail, tuple['Naics', Report|None, Company|None]]):
    id: Mapped[int] = mapped_column(Integer(), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    reports: Mapped[list[Report]] = relationship(secondary=NaicsReport, back_populates='naics')

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
        if lazy:
            yield_per = lazy if lazy > 1 else DEFAULT_YIELD_PER
            stmt = stmt.execution_options(yield_per=yield_per)
        return stmt

    @classmethod
    def reduce_init(cls, row, memo):
        inst = super().reduce_init(row, memo)
        inst.root = int(str(inst.id)[:2])
        return inst

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

class Artifact(Base[ArtifactDetail, tuple['Artifact', Report|None]]):
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
        if lazy:
            yield_per = lazy if lazy > 1 else DEFAULT_YIELD_PER
            stmt = stmt.execution_options(yield_per=yield_per)
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

def migrate() -> None:
    import alembic.command
    from alembic.config import Config
    config = Config(settings.ALEMBIC_INI)
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        alembic.command.upgrade(config, 'head')
    with SessionLocal() as session:
        exists = bool(
            session
            .execute(select(Naics.id).limit(1))
            .scalar_one_or_none())
    if not exists:
        load_naics()

def load_naics() -> None:
    logger.info(f'Loading NAICS')
    import requests
    rep = requests.get(settings.NAICS_DOWNLOAD)
    rep.raise_for_status()
    records = (
        dict(
            id=entry['code'],
            code=entry['code_raw'],
            title=entry['title'])
        for entry in rep.json())
    with SessionLocal() as session:
        session.add_all(Naics(**record) for record in records)
        session.commit()

actions = dict(migrate=migrate, naics=load_naics)

class Command(utils.BaseCommand):

    @classmethod
    def add_arguments(cls, parser) -> None:
        parser.add_argument('action', choices=actions)

    def run(self):
        actions[self.opts.action]()

if __name__ == '__main__':
    Command.main()
