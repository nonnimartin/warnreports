class SqlSearch(BaseSearch[orm.ModelSelect, DM]):
    sql_model_class: ClassVar[orm.Model]
    sql_joins: ClassVar[Sequence[tuple]] = ()
    sql_group_by: ClassVar[Sequence] = ()
    alias_fieldmap: ClassVar[dict[str, orm.Alias]] = {}
    order_fieldmap: ClassVar[dict[str, orm.Field]] = {}

    def get_queryset(self):
        qs = self.sql_model_class.select(*self.get_selects())
        for join in self.get_joins():
            qs = qs.join_from(*join)
        group_by = list(self.get_group_by())
        if group_by:
            qs = qs.group_by(*group_by)
        return qs

    def get_selects(self):
        yield self.sql_model_class
        yield from self.alias_fieldmap.values()

    def get_group_by(self):
        yield from self.sql_group_by

    def get_joins(self):
        yield from self.sql_joins

    def filter_queryset(self, qs):
        filters = list(self.get_filters())
        return qs.where(*filters) if filters else qs

    def order_queryset(self, qs):
        orders = list(self.get_ordering())
        return qs.order_by(*orders) if orders else qs

    def paginate_queryset(self, qs, limit, offset):
        if limit:
            qs = qs.limit(limit)
        if offset:
            qs = qs.offset(offset)
        return qs

    def get_ordering(self):
        fieldmap = ChainMap(self.order_fieldmap, self.alias_fieldmap)
        for field, dir_ in super().get_ordering():
            if field in fieldmap:
                ormfield = fieldmap[field]
                if dir_ == -1:
                    ormfield = ormfield.desc()
                yield ormfield

    @staticmethod
    def wc_contains(text: str) -> str:
        return f'%{text}%'

    @staticmethod
    def wc_startswith(text: str) -> str:
        return f'{text}%'

class SqlReportsFilter(ReportsFilter, SqlSearch[ReportData]):
    sql_model_class: ClassVar = Report
    order_fieldmap: ClassVar = {
        'reported': Report.reported,
        'starting': Report.starting,
        'employees': Report.employees,
        'state': Report.state.collate('NOCASE'),
        'company': Report.company.collate('NOCASE'),
        'action': Report.action.collate('NOCASE'),
    }

    def get_filters(self):
        if self.id:
            yield Report.id == self.id
        if self.state:
            yield Report.state == self.state
        if self.company:
            yield Report.company.ilike(self.wc_contains(self.company))
        if self.action:
            yield Report.action.ilike(self.wc_contains(self.action))
        if self.location:
            yield Report.location.ilike(self.wc_contains(self.location))
        if self.text:
            wc = self.wc_contains(self.text)
            yield Report.company.ilike(wc) | Report.location.ilike(wc)
        if self.reported_before:
            yield Report.reported < self.reported_before
        if self.reported_after:
            yield Report.reported > self.reported_after
        if self.starting_before:
            yield Report.starting < self.starting_before
        if self.starting_after:
            yield Report.starting > self.starting_after
        if self.employees_lt is not None:
            yield Report.employees < self.employees_lt
        if self.employees_gt is not None:
            yield Report.employees > self.employees_gt

class SqlCompaniesFilter(CompaniesFilter, SqlSearch[CompanyDetail]):
    sql_model_class: ClassVar = Report
    sql_group_by: ClassVar = [Report.company, Report.state]
    alias_fieldmap: ClassVar = {
        'reports_count': orm.fn.Count(Report.id).alias('reports_count'),
        'last_reported': orm.fn.Max(Report.reported).alias('last_reported'),
    }
    order_fieldmap: ClassVar = SqlReportsFilter.order_fieldmap

    def get_filters(self):
        yield from SqlReportsFilter(**self.model_dump()).get_filters()
        if self.reports_count_lt:
            alias = self.alias_fieldmap['reports_count']
            yield alias < self.reports_count_lt
        if self.reports_count_gt:
            alias = self.alias_fieldmap['reports_count']
            yield alias > self.reports_count_gt
        if self.last_reported_before:
            alias = self.alias_fieldmap['last_reported']
            yield alias < self.last_reported_before
        if self.last_reported_after:
            alias = self.alias_fieldmap['last_reported']
            yield alias > self.last_reported_after

class SqlStatesFilter(StatesFilter, SqlSearch[StateDetail]):
    sql_model_class: ClassVar = Report
    sql_group_by: ClassVar = [Report.state]
    alias_fieldmap: ClassVar = SqlCompaniesFilter.alias_fieldmap
    order_fieldmap: ClassVar = SqlCompaniesFilter.order_fieldmap
    get_filters = SqlCompaniesFilter.get_filters

class SqlNaicsFilter(NaicsFilter, SqlSearch[NaicsDetail]):
    sql_model_class: ClassVar = Naics
    sql_group_by: ClassVar = [Naics]
    sql_joins: ClassVar = [(Naics, NaicsReport, orm.JOIN['LEFT_OUTER'])]
    alias_fieldmap: ClassVar[dict[str, orm.Alias]] = {
        'reports_count': orm.fn.Count(NaicsReport.id).alias('reports_count'),
    }
    order_fieldmap: ClassVar = {
        'id': Naics.id,
        'code': Naics.code,
        'title': Naics.title.collate('NOCASE'),
    }

    def get_filters(self):
        if self.id is not None:
            yield Naics.id == self.id
        if self.code is not None:
            yield Naics.id == self.code
        if self.prefix:
            wc = self.wc_startswith(str(self.prefix))
            logger.info(f'{wc=}')
            yield (Naics.id == self.prefix) | Naics.code.ilike(wc)
        if self.title:
            wc = self.wc_contains(self.title)
            yield Naics.title.ilike(wc)
        if self.text:
            wc1 = self.wc_startswith(str(self.text))
            wc2 = self.wc_contains(self.text)
            yield Naics.title.ilike(wc2) | Naics.code.ilike(wc1)
        if self.reports_count_lt is not None:
            alias = self.alias_fieldmap['reports_count']
            yield alias < self.reports_count_lt
        if self.reports_count_gt is not None:
            alias = self.alias_fieldmap['reports_count']
            yield alias > self.reports_count_gt