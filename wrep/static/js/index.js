import {createTableComponent, ReportColumns} from './table.js'

const defn = {
    id: 'reports_recent',
    title: 'Recent 50+ employees',
    url: '/api/v0/reports',
    params: {employees_min: 50, order: '-reported'},
    columns: ReportColumns,
}

const opts = {
    order: [{name: 'reported', dir: 'desc'}],
    pageLength: 25,
    autoWidth: false,
}

$(() => {
    const main = $('#id_maincontent')
    main.append(createTableComponent(defn, opts))
})
