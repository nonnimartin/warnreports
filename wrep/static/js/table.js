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

export const serverSide = {
    processing: true,
    serverSide: true,
    ajax: {
        url: '/dt/reports',
        data: data => cleanDtParams(data)
    },
}

export const slim = {
    pageLength: 10,
    ordering: false,
    lengthChange: false,
    filter: false,
    layout: {
        bottomStart: null
    },
}

export function getServerSideOpts(params) {
    const parts = [serverSide.ajax.url]
    if (params) {
        parts.push(new URLSearchParams(params).toString())
    }
    const url = parts.join('?')
    return $.extend(true, {}, serverSide, {ajax: {url}})
}

function cleanDtParams(data) {
    data.limit = data.length
    data.offset = data.start
    delete data.length
    delete data.start
    delete data.columns
    delete data.search
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

export function initTable(table, params, ...args) {
    const optsets = [defaults, getServerSideOpts(params)]
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