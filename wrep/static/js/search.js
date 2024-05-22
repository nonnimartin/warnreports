import {getFormParams} from './main.js'
import {defaults as _defaults, serverSide} from './table.js'

export const defaults = $.extend(true, {}, _defaults, {
    layout: {
        topEnd: null,
        bottomStart: 'pageLength',
        bottomEnd: 'paging',
        bottom2Start: 'info'
    },
})

export function initSearchTable(table, form, ...args) {
    const optsets = [
        defaults,
        {layout: {topStart: form}},
        getServerSideOpts(form),
        getStateSaveOpts(form),
    ]
    const opts = $.extend(true, {}, ...optsets, ...args)
    const dt = table.DataTable(opts)
    initSearchForm(form, table)
    return dt
}

const REDRAW_DELAY = 100

function setSearchPayload(data, form) {
    const params = getFormParams(form)
    for (const key of params.keys()) {
        data[key] = params.getAll(key).join(',')
    }
    if (data.text && data.text.length < 2) {
        delete data.text
    }
}

function setStateSaveParams(data, form) {
    const params = getFormParams(form)
    Object.assign(data, Object.fromEntries(params.entries()))
}

function loadStateSaveParams(data, form) {
    for (const key of new FormData($(form).get(0)).keys()) {
        if (data[key]) {
            $(`:input[name="${key}"]`, form).val(data[key])
        }
    }
}

function getServerSideOpts(form) {
    const data = data => {
        serverSide.ajax.data(data)
        if (form && form.length) {
            setSearchPayload(data, form)
        }
    }
    return $.extend(true, {}, serverSide, {ajax: {data}})
}

function getStateSaveOpts(form) {
    return {
        stateSave: true,
        stateSaveParams: (settings, data) => setStateSaveParams(data, form),
        stateLoadParams: (settings, data) => loadStateSaveParams(data, form),
    }
}

function initSearchForm(form, table) {
    const clearForm = $('.clear-form', form)
    const dt = table.DataTable()
    const doDraw = dt.draw.bind(dt)
    let reqTimeout
    const queueDraw = () => {
        clearTimeout(reqTimeout)
        reqTimeout = setTimeout(doDraw, REDRAW_DELAY)
    }
    form
        .on('submit', e => {
            e.preventDefault()
            queueDraw()
        })
        .on('change keyup keydown', queueDraw)
    clearForm.on('click', e => {
        e.preventDefault()
        $(':input', form).val('')
        dt.state({order: defaults.order})
        clearTimeout(reqTimeout)
        doDraw()
    })
}

$(() => {
    $('.reports-auto-search').each(function() {
        initSearchTable($('table', this), $('form.search-form', this))
    })
})
