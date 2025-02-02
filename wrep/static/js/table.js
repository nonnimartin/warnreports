export const defaults = {
    columns: [
        {name: 'state'},
        {name: 'company', render: renderCompany},
        {name: 'reported', render: renderDate, type: 'date'},
        {name: 'starting', render: renderDate, type: 'date'},
        {name: 'employees', type: 'num'},
        {name: 'action', render: renderAction, orderable: false},
    ],
    order: [{name: 'reported', dir: 'desc'}],
    pageLength: 25,
    autoWidth: false,
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

function getServerSideOpts(coll, params) {
    params = params || {}
    return {
        processing: true,
        serverSide: true,
        ajax: async (data, callback, settings) => {
            callback(await dtAjax(coll, {...data, ...params}))
        },
    }
}

export async function dtAjax(coll, params) {
    params = {...params}
    cleanDtParams(params)
    const {draw} = params
    delete params.draw
    const recordsTotal = await getRecordsTotal(coll)
    const res = await aajax({url: `/api/v0/${coll}`, method: 'GET', data: params})
    const xhr = res[2]
    return {
        data: res[0],
        recordsFiltered: +xhr.getResponseHeader(coll),
        recordsTotal,
        draw
    }
}

function cleanDtParams(data) {
    if (!Object.hasOwn(data, 'limit')) {
        data.limit = data.length
    }
    if (!Object.hasOwn(data, 'offset')) {
        data.offset = data.start
    }
    delete data.length
    delete data.start
    delete data.columns
    delete data.search
    if (Array.isArray(data.order)) {
        const orders = []
        for (let {name, dir} of data.order) {
            if (dir === 'desc') {
                name = `-${name}`
            }
            orders.push(name)
        }
        delete data.order
        if (orders.length) {
            data.order = orders.join(',')
        }
    }
}

const RecordsTotalExpiry = 30 * 1000
const RecordsTotalCache = new Map

export async function getRecordsTotal(coll) {
    let cache = RecordsTotalCache.get(coll)
    if (!cache) {
        cache = {value: null, at: null}
        RecordsTotalCache.set(coll, cache)
    }
    if (cache.value === null || cache.at < +new Date - RecordsTotalExpiry) {
        const res = await aajax({url: `/api/v0/${coll}`, method: 'HEAD'})
        let value = +res[2].getResponseHeader('count')
        let at = null
        if (isNaN(value)) {
            value = null
        } else {
            at = +new Date
        }
        Object.assign(cache, {value, at})
    }
    return cache.value
}

function aajax(...args) {
    return new Promise((resolve, reject) => {
        $.ajax(...args)
            .done((...args) => resolve(args))
            .fail((xhr, textStatus, errorThrown) => reject(errorThrown))
    })
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

function initTable(table, params, ...args) {
    const optsets = [defaults, getServerSideOpts('reports', params)]
    const opts = $.extend(true, {}, ...optsets, ...args)
    return table.DataTable(opts)
}

$(() => {
    $('.reports-auto-table').each(function() {
        const wrapper = $(this)
        const table = $('table', wrapper)
        if (!table.length) {
            return
        }
        const {queryId} = wrapper.data()
        const params = queryId
            ? JSON.parse($(`script#${queryId}`).html())
            : null
        const optsets = []
        if (wrapper.hasClass('slim')) {
            optsets.push(slim)
        }
        const dt = initTable(table, params, ...optsets)
        if (wrapper.hasClass('hide-empty')) {
            const cb = () => {
                const {data} = dt.ajax.json()
                wrapper.toggle(Boolean(data.length))
                dt.off('xhr', cb)
            }
            dt.on('xhr', cb)
        }
    })
})