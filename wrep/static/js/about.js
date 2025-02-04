import {nf} from './main.js'
import {createTableComponent} from './table.js'


function renderDate(value) {
    return value ? value.substring(0, 10) : ''
}

function renderState(value, type, row) {
    return $('<a/>')
        .attr({href: `/feed?state=${row.id}`, title: value})
        .text(row.id)
        .get(0)
        .outerHTML
}

const opts = {
    paging: false,
    filter: false,
    layout: {
        bottomStart: null,
    },
}
const Columns = {
    reports_count: {title: 'Reports', name: 'reports_count', render: nf, type: 'num'},
}

const reports_count = {title: 'Reports', name: 'reports_count', render: nf, type: 'num'}
const defns = [
    {
        id: 'collection_stats',
        title: 'Collection Stats',
        url: '/api/v0/_db',
        columns: [
            {title: 'Name', name: 'name'},
            {title: 'Records', name: 'count', render: nf, type: 'num'},
            {title: 'Size', name: 'size', render: nf, type: 'num'},
        ],
        data: data => {
            const records = []
            for (const [name, record] of Object.entries(data.collections)) {
                record.name = name
                records.push(record)
            }
            return records
        },
    },
    {
        id: 'state_stats',
        title: 'State Stats',
        url: '/api/v0/states',
        columns: [
            {title: 'State', name: 'id', render: renderState},
            reports_count,
            {title: 'Last Reported', name: 'last_reported', render: renderDate, type: 'date'},
        ],
    },
    {
        id: 'naics_stats',
        title: 'NAICS Stats',
        url: '/api/v0/naics',
        params: {reports_count_min: 1, depth_max: 0},
        columns: [
            {title: 'ID', name: 'id'},
            {title: 'Title', name: 'title'},
            reports_count,
        ],
    }
]

export async function renderPage(target) {
    target = $(target).empty()
    for (const defn of defns) {
        target.append(createTableComponent(defn, opts))
    }
}
