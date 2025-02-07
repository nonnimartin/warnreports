import { ReportColumns, TableComponent } from '../lib/table.js'

export default new TableComponent({
    id: 'reports_recent',
    title: 'Recent 50+ employees',
    collection: 'reports',
    params: {employees_min: 50, order: '-reported'},
    columns: ReportColumns,
    opts: {
        pageLength: 10,
        ordering: false,
        lengthChange: false,
        filter: false,
        layout: {
            bottomStart: null,
        },
        autoWidth: false,
    },
})
