import {aajax, nf} from './main.js'

export const defaults = {
    columns: [
        {title: 'State', name: 'state'},
        {title: 'Company', name: 'company', render: renderCompany},
        {title: 'Reported', name: 'reported', render: renderDate, type: 'date'},
        {title: 'Starting', name: 'starting', render: renderDate, type: 'date'},
        {title: 'Employees', name: 'employees', type: 'num'},
        {title: 'Action', name: 'action', render: renderAction, orderable: false},
    ],
    order: [{name: 'reported', dir: 'desc'}],
    pageLength: 25,
    autoWidth: false,
}

export const ReportColumns = [
    {title: 'State', name: 'state'},
    {title: 'Company', name: 'company', render: renderCompany},
    {title: 'Reported', name: 'reported', render: renderDate, type: 'date'},
    {title: 'Starting', name: 'starting', render: renderDate, type: 'date'},
    {title: 'Employees', name: 'employees', render: nf, type: 'num'},
    {title: 'Action', name: 'action', render: renderAction, orderable: false},
]

for (const c of defaults.columns) {
    c.data = c.data || c.name

}
const slim = {
    pageLength: 10,
    ordering: false,
    lengthChange: false,
    filter: false,
    layout: {
        bottomStart: null
    },
}

function getServerSideOpts(collection, params) {
    params = params || {}
    return {
        processing: true,
        serverSide: true,
        ajax: async (data, callback, settings) => {
            callback(await dtAjax(collection, {...data, ...params}))
        },
    }
}

export async function dtAjax(collection, params) {
    params = cleanDtParams(params)
    const {draw} = params
    delete params.draw
    const opts = {url: `/api/v0/${collection}`, method: 'GET', data: params}
    const tasks = [getCollectionStats(), aajax(opts)]
    const {body, xhr} = await tasks.pop()
    const stats = await tasks.pop()
    return {
        data: body,
        recordsFiltered: +xhr.getResponseHeader('count'),
        recordsTotal: stats.get(collection).count,
        draw
    }
}

function cleanDtParams(params) {
    params = {...params}
    params.limit = params.length
    params.offset = params.start
    delete params.length
    delete params.start
    delete params.columns
    delete params.search
    const orders = []
    for (let {name, dir} of params.order) {
        if (dir === 'desc') {
            name = `-${name}`
        }
        orders.push(name)
    }
    delete params.order
    if (orders.length) {
        params.order = orders.join(',')
    }
    return params
}

const CollectionStats = new Map
CollectionStats.expiry = 1 * 60 * 1000
CollectionStats.at = null

async function getCollectionStats() {
    const cache = CollectionStats
    if (cache.size === 0 || cache.at < +new Date - cache.expiry) {
        const {body} = await aajax({url: '/api/v0/_db'})
        cache.clear()
        for (const entry of Object.entries(body.collections)) {
            cache.set(...entry)
        }
        cache.at = +new Date
    }
    return cache
}

const StateIds = []

export async function getAllStateIds() {
    if (!StateIds.length) {
        const {body} = await aajax({url: '/api/v0/states'})
        for (const state of body) {
            StateIds.push(state.id)
        }
    }
    return StateIds
}

function renderDate(value) {
    return value ? value.substring(0, 10) : ''
}

function strunc(str, len) {
    if (str.length > len) {
        str = str.substring(0, len - 4) + ' ...'
    }
    return str
}

function renderCompany(value, type, row) {
    return $('<a/>')
        .attr({href: `/r/${row.id}`, title: value})
        .text(strunc(value, 50))
        .get(0)
        .outerHTML
}

function renderAction(value) {
    if (!value) {
        return ''
    }
    return $('<span/>')
        .attr({title: value})
        .text(strunc(value, 40))
        .get(0)
        .outerHTML
}

async function initTable(table, params, ...args) {
    const optsets = [defaults, getServerSideOpts('reports', params)]
    const opts = $.extend(true, {}, ...optsets, ...args)
    return table.DataTable(opts)
}

function getDefnTableOpts(defn) {
    const {columns} = defn
    for (const c of columns) {
        c.data = c.data || c.name
    }
    const ajax = {dataSrc: defn.data || '', url: defn.url}
    if (defn.params) {
        ajax.url += '?' + new URLSearchParams(defn.params).toString()
    }
    const opts = {columns, ajax}
    return opts
}

export function createTableComponent(defn, opts) {
    opts = opts || {}
    opts = {...opts, ...getDefnTableOpts(defn)}
    const table = $('<table/>')
        .addClass(['table', 'table-striped', 'responsive'])
    const wrapper = $('<div/>')
        .attr({id: defn.id})
        .append([
            $('<h2/>').text(defn.title),
            table,
        ])
    table.DataTable(opts)
    return wrapper
}

$(async () => {
    
    for (const el of $('.reports-auto-table').toArray()) {
        const wrapper = $(el)
        const table = $('table', wrapper)
        if (!table.length) {
            continue
        }
        const {queryId} = wrapper.data()
        const params = queryId
            ? JSON.parse($(`script#${queryId}`).html())
            : null
        const optsets = []
        if (wrapper.hasClass('slim')) {
            optsets.push(slim)
        }
        const dt = await initTable(table, params, ...optsets)
        if (wrapper.hasClass('hide-empty')) {
            const cb = () => {
                const {data} = dt.ajax.json()
                wrapper.toggle(Boolean(data.length))
                dt.off('xhr', cb)
            }
            dt.on('xhr', cb)
        }
    }
})