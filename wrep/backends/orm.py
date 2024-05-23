from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Generic

from sqlalchemy import (UUID, BigInteger, Boolean, Column, DateTime, select,
                        ForeignKey, Integer, String, Table, create_engine)
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column,joinedload, aliased,
                            relationship, sessionmaker)
from sqlalchemy.sql import func

from .. import settings, utils
from ..models import ReportData, NaicsData, ArtifactData, DM, ArtifactDetail, NaicsDetail, CompanyDetail
engine = create_engine(settings.DB_URL, echo=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase, Generic[DM]):

    @classmethod
    def select_for_reduce(cls):
        return select(cls)

    def reduce(self, obj: DM, memo: dict[str, set]) -> None:
        pass

    @classmethod
    def reduce_end(cls, obj: DM, memo: dict[str, set]) -> None:
        pass

NaicsReport = Table(
    'naicsreport',
    Base.metadata,
    Column('naics_id', ForeignKey('naics.id'), primary_key=True),
    Column('report_id', ForeignKey('report.id'), primary_key=True),
)
ArtifactReport = Table(
    'artifactreport',
    Base.metadata,
    Column('artifact_id', ForeignKey('artifact.id'), primary_key=True),
    Column('report_id', ForeignKey('report.id'), primary_key=True),
)

class Report(Base):
    __tablename__ = 'report'
    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    company: Mapped[str] = mapped_column(String(512), index=True)
    company_norm: Mapped[str] = mapped_column(String(512), index=True)
    reported: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(2), index=True)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    location: Mapped[str|None] = mapped_column(String(255), nullable=True)
    starting : Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    employees: Mapped[int] = mapped_column(Integer(), nullable=True)
    action: Mapped[str|None] = mapped_column(String(64), nullable=True)
    url: Mapped[str|None] = mapped_column(String(2083), nullable=True)
    naics: Mapped[List[Naics]] = relationship(secondary=NaicsReport, back_populates='reports')
    artifacts: Mapped[List[Artifact]] = relationship(secondary=ArtifactReport, back_populates='reports')


    @classmethod
    def select_for_reduce(cls):
        return (
            select(
                cls,
                CompanyReport := aliased(cls),
                Naics,
                Artifact)
            .join(
                CompanyReport,
                onclause=(cls.company_norm == CompanyReport.company_norm))
            # .join(
            #     NaicsReport,
            #     isouter=True,
            #     onclause=(CompanyReport.id == NaicsReport.report_id)
            # )
            .join(
                CompanyReport.naics,
                isouter=True,
                # onclause=(NaicsReport.naics_id == Naics.id)
            )
            .options(joinedload(CompanyReport.naics))
            .join(cls.artifacts, isouter=True)
            # .join_from(cls, Artifact, isouter=True)
            .options(joinedload(cls.artifacts))
            .order_by(cls.id, Naics.code, Artifact.id)
            )
        raise NotImplementedError
        return (cls
            .select(
                cls,
                CompanyReport := cls.alias(),
                NaicsReport,
                Naics,
                ArtifactReport,
                Artifact)
            .join(
                CompanyReport,
                attr='company_report',
                on=(cls.company_norm == CompanyReport.company_norm))
            .join(NaicsReport, LEFT_OUTER)
            .join(Naics, LEFT_OUTER)
            .switch(cls)
            .join(ArtifactReport, LEFT_OUTER)
            .join(Artifact, LEFT_OUTER)
            .order_by(cls.id, Naics.code, Artifact.id))


    def reduce(self, report: ReportData, memo: dict[str, set]) -> None:
        if not report.company_id:
            report.company_id = uuid.uuid5(Company.NS, self.company_norm)
        for naics in self.naics:
            if naics not in memo['naics']:
                report.naics.append(NaicsData.model_validate(naics))
                memo['naics'].add(naics)
        for artifact in self.artifacts:
            if artifact not in memo['artifacts']:
                report.artifacts.append(ArtifactData.model_validate(artifact))
                memo['artifacts'].add(artifact)
        return
        nr: NaicsReport|None = getattr(obj.company_report, 'naicsreport', None)
        if nr and nr.naics not in memo['naics']:
            naics = NaicsData.model_validate(nr.naics)
            self.naics.append(naics)
            memo['naics'].add(nr.naics)
        ar: ArtifactReport|None = getattr(obj, 'artifactreport', None)
        if ar and ar.artifact not in memo['artifacts']:
            artifact = ArtifactData.model_validate(ar.artifact)
            self.artifacts.append(artifact)
            memo['artifacts'].add(ar.artifact)

    @classmethod
    def reduce_end(cls, report: ReportData, memo: dict[str, set]) -> None:
        report.naics.sort(key=lambda x: (x.code, x.id))
    '''
    stmt = select(my.Report, my.Artifact).join(my.Report.artifacts).options(joinedload(my.Report.artifacts))
    '''

class StateStat(Base):
    __tablename__ = 'statestat'
    id: Mapped[str] = mapped_column(String(2), primary_key=True)
    last_reported: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    reports_count: Mapped[int] = mapped_column(Integer(), default=0)

    def self_update(self):
        raise NotImplementedError
        q = Report.select(Report.reported).where(Report.state == self.id)
        self.reports_count = q.count()
        latest = q.order_by(Report.reported.desc()).limit(1).first()
        self.last_reported = latest and latest.reported

class Company(Base[CompanyDetail]):
    __tablename__ = 'company'
    NS = uuid.uuid5(settings.NAMESPACE, 'Company')
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(512), unique=True)
    name_norm: Mapped[str] = mapped_column(String(512), index=True)
    name_canon: Mapped[str] = mapped_column(String(512), index=True)
    # reports: Mapped[list[Report]] = relationship(Report, primaryjoin='foreign(Company.name_norm) == Report.company_norm')

    @classmethod
    def select_for_reduce(cls):
        from sqlalchemy.orm import Bundle
        ReportAlias = aliased(Report, name='report')
        return (
            select(
                cls,
                # Bundle('report', ReportAlias := aliased(Report, name='report')),
                Bundle('report', ReportAlias.id, ReportAlias.employees, ReportAlias.state),
                Bundle('naics', Naics.id, Naics.title, Naics.code),
                # ReportAlias := aliased(Report),
                # ReportAlias := aliased(Report, name='report'),
                # Naics,
                # ReportAlias.naics
                )
            .join(
                ReportAlias,
                # isouter=True,
                onclause=(ReportAlias.company_norm == cls.name_norm))
            # .options(joinedload(ReportAlias))
            .join(ReportAlias.naics, isouter=True)
            # .options(joinedload(ReportAlias.naics))
            # .order_by(cls.name_norm, cls.name, ReportAlias.state, Naics.id)
            )
        return (cls
            .select(
                cls,
                Report,
                NaicsReport,
                Naics)
            .join(
                Report,
                LEFT_OUTER,
                on=(Report.company_norm == cls.name_norm))
            .join(NaicsReport, LEFT_OUTER)
            .join(Naics, LEFT_OUTER)
            .order_by(cls.name_norm, cls.name, Report.state, Naics.id))


    def reduce(self, obj, memo):
        if not memo['normed']:
            obj.id = uuid.uuid5(Company.NS, self.name_norm)
            memo['normed'].add(True)
        memo['canon'].add(self.name_canon)
        if self.name_canon not in memo['aliases']:
            obj.aliases.append(self.name_canon)
            memo['aliases'].add(self.name_canon)
        if self.name not in memo['aliases']:
            obj.aliases.append(self.name)
            memo['aliases'].add(self.name)

        if not memo['normed']:
            self.id = uuid.uuid5(Company.NS, obj.name_norm)
            memo['normed'].add(True)
        memo['canon'].add(obj.name_canon)
        if obj.name_canon not in memo['aliases']:
            self.aliases.append(obj.name_canon)
            memo['aliases'].add(obj.name_canon)
        if obj.name not in memo['aliases']:
            self.aliases.append(obj.name)
            memo['aliases'].add(obj.name)

        report: Report = getattr(obj, 'report', None)
        if report and report not in memo['reports']:
            self.reports_count += 1
            if report.employees:
                self.employees_sum += report.employees
            self.last_reported = max(filter(None, (self.last_reported, report.reported)))
            memo['reports'].add(report)
            if report.state not in memo['states']:
                self.states.append(report.state)
                memo['states'].add(report.state)
            nr: NaicsReport|None = getattr(report, 'naicsreport', None)
            if nr and nr.naics not in memo['naics']:
                naics = NaicsData.model_validate(nr.naics)
                self.naics.append(naics)
                memo['naics'].add(nr.naics)

    def reduce_end(self, memo):
        self.name = sorted(memo['canon'], key=normls.company_name_sort)[0]
        self.aliases.sort(key=lambda x: (x.lower(), x))
        self.naics.sort(key=lambda x: (x.code, x.id))
        self.states.sort()

    def equals_obj(self, obj: Company) -> bool:
        return obj.name_norm == normls.company_name_norm(self.name)

class Naics(Base[NaicsDetail]):
    __tablename__ = 'naics'
    id: Mapped[int] = mapped_column(Integer(), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    reports: Mapped[List[Report]] = relationship(secondary=NaicsReport, back_populates='naics')

    @classmethod
    def select_for_reduce(cls):
        return (
            select(cls, Report)
            .join(cls.reports, isouter=True)
            .join(
                Company,
                isouter=True,
                onclause=(Report.company_norm == Company.name_canon))
            .options(joinedload(cls.reports))
            .order_by(cls.id))
        return (cls
            .select(NaicsReport, Report, cls)
            .join(NaicsReport, LEFT_OUTER)
            .join(Report, LEFT_OUTER)
            .join(
                Company,
                LEFT_OUTER,
                on=(Report.company_norm == Company.name_norm))
            .order_by(cls.id))


    def reduce(self, obj, memo) -> None:
        for report in self.reports:
            if report in memo['reports']:
                continue
            obj.reports_count += 1
            if report.employees:
                obj.employees_sum += report.employees
            memo['reports'].add(report)
            if report.company_norm not in memo['companies']:
                obj.companies_count == 1
                memo['companies'].add(report.company_norm)
        return
        nr: NaicsReport|None = getattr(obj, 'naicsreport', None)
        if nr and nr.report not in memo['reports']:
            self.reports_count += 1
            if nr.report.employees:
                self.employees_sum += nr.report.employees
            memo['reports'].add(nr.report)
            company: str|None = getattr(nr.report, 'company_norm', None)
            if company and company not in memo['companies']:
                self.companies_count += 1
                memo['companies'].add(company)

class Artifact(Base[ArtifactDetail]):
    __tablename__ = 'artifact'
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(2083), unique=True)
    url: Mapped[str] = mapped_column(String(2083))
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    modified: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    mimetype: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(BigInteger())
    sha1: Mapped[str] = mapped_column(String(40))
    reports: Mapped[List[Report]] = relationship(secondary=ArtifactReport, back_populates='artifacts')

    @property
    def name(self):
        return Path(self.path).name

    @classmethod
    def select_for_reduce(cls):
        return (
            select(cls, Report)
            .join(cls.reports, isouter=True)
            .options(joinedload(cls.reports))
            .order_by(cls.id))


    def reduce(self, obj, memo) -> None:
        for report in self.reports:
            if report not in memo['reports']:
                obj.reports_count += 1
                memo['reports'].add(report)
        return
        ar: ArtifactReport|None = getattr(obj, 'artifactreport', None)
        if ar and ar.report not in memo['reports']:
            self.reports_count += 1
            memo['reports'].add(ar.report)

    def self_update(self) -> None:
        file = Path(settings.ARTIFACTS_DIR, self.path)
        with file.open('rb') as f:
            digest = hashlib.file_digest(f, 'sha1')
        stat = file.stat()
        data = dict(
            size=stat.st_size,
            modified=datetime.fromtimestamp(stat.st_mtime),
            mimetype=utils.get_mimetype(file),
            sha1=digest.hexdigest())
        for field, value in data.items():
            if getattr(self, field) != value:
                setattr(self, field, value)

'''
from sqlalchemy.orm import Session; from sqlalchemy import select; from wrep.backends import orm as my; session = Session(my.engine)


from sqlalchemy.orm import Session
from sqlalchemy import select
from wrep.backends import orm as my
session = Session(my.engine)
stmt = my.Company.select_for_reduce()
stmt = stmt.limit(5000)
rs = list(session.execute(stmt).unique().scalars())
'''