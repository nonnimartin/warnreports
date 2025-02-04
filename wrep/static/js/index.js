import {createTableComponent, ReportColumns} from './table.js'

const defn = {
    id: 'reports_recent',
    title: 'Recent 50+ employees',
    collection: 'reports',
    params: {employees_min: 50, order: '-reported'},
    columns: ReportColumns,
}

const opts = {
    pageLength: 10,
    ordering: false,
    lengthChange: false,
    filter: false,
    layout: {
        bottomStart: null
    },
}

export async function renderPage(target) {
    $(target).html(createTableComponent(defn, opts))
}
