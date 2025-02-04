import {aajax, nf} from './main.js'

export function createTableComponent(defn, opts) {
    opts = opts || {}
    opts = {...opts, ...getDefnTableOpts(defn)}
    const table = $('<table/>')
        .addClass(['table', 'table-striped', 'responsive'])
    const wrapper = $('<div/>')
    if (defn.id) {
        wrapper.attr({id: defn.id})
    }
    if (defn.title) {
        wrapper.append($('<h2/>').text(defn.title))
    }
    wrapper.append(table)
    const dt = table.DataTable(opts)
    dt.on('init', (e, settings, json) => {
        if (wrapper.hasClass('hide-empty')) {
            let length
            if (Array.isArray(json)) {
                length = json.length
            } else if (typeof json.recordsTotal === 'number') {
                length = json.recordsFiltered
            }
            wrapper.toggle(Boolean(length))
            if (length) {
                dt.draw()
            }
        }
    })
    return wrapper
}

export const ReportFieldRender = {
    company: renderCompany,
    reported: renderDate,
    starting: renderDate,
    employees: nf,
    action: renderAction,
    url: renderUrl,
}

const column = (name, opts) => ({name, render: ReportFieldRender[name], ...(opts || {})})

export const ReportColumns = [
    column('state', {title: 'State'}),
    column('company', {title: 'Company'}),
    column('reported', {title: 'Reported', type: 'date'}),
    column('starting', {title: 'Starting', type: 'date'}),
    column('employees', {title: 'Employees', type: 'num'}),
    column('action', {title: 'Action', orderable: false}),
]

export async function populateStateSelects(form) {
    const stateSelects = $('select[name="state"]', form).toArray()
    if (stateSelects.length) {
        const stateIds = await getAllStateIds()
        for (const select of stateSelects) {
            for (const id of stateIds) {
                $('<option/>').attr({value: id}).text(`${id}`).appendTo(select)
            }
        }
    }
}

async function dtAjax(collection, params) {
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
    if (typeof params.order === 'string') {
        orders.push(params.order)
    } else {
        for (let {name, dir} of params.order) {
            if (dir === 'desc') {
                name = `-${name}`
            }
            orders.push(name)
        }
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

async function getAllStateIds() {
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

function renderUrl(value) {
    if (!value) {
        return ''
    }
    return $('<a/>')
        .attr({href: value, target: '_blank'})
        .text(value)
        .get(0)
        .outerHTML

}

function getDefnTableOpts(defn) {
    const {columns, collection, params} = defn
    for (const c of columns) {
        c.data = c.data || c.name
    }
    const opts = {columns}
    if (collection) {
        opts.ajax = async (data, callback, settings) => {
            if (params) {
                if (typeof params === 'function') {
                    const ret = await params(data)
                    if (ret) {
                        data = ret
                    }
                } else {
                    data = {...data, ...params}
                }
            }
            callback(await dtAjax(collection, data))
        }
        opts.processing = true
        opts.serverSide = true
    } else {
        opts.ajax = {dataSrc: defn.data || '', url: defn.url}
        if (params) {
            opts.ajax.url += '?' + new URLSearchParams(params).toString()
        }
    }
    return opts
}
