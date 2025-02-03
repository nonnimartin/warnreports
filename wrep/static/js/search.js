import {getFormParams} from './main.js'
import {defaults as _defaults, dtAjax, getAllStateIds} from './table.js'

const defaults = $.extend(true, {}, _defaults, {
    layout: {
        topEnd: null,
        bottomStart: 'pageLength',
        bottomEnd: 'paging',
        bottom2Start: 'info'
    },
})


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
    return {
        processing: true,
        serverSide: true,
        ajax: async (data, callback, settings) => {
            if (form && form.length) {
                setSearchPayload(data, form)
            }
            callback(await dtAjax('reports', data))
        }
    }
}

function getStateSaveOpts(form) {
    return {
        stateSave: true,
        stateSaveParams: (settings, data) => setStateSaveParams(data, form),
        stateLoadParams: (settings, data) => loadStateSaveParams(data, form),
    }
}

async function initSearchForm(form, table) {
    const stateSelects = $('select[name="state"]', form).toArray()
    if (stateSelects.length) {
        const stateIds = await getAllStateIds()
        for (const select of stateSelects) {
            for (const id of stateIds) {
                $('<option/>').attr({value: id}).text(`${id}`).appendTo(select)
            }
        }
    }
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
const formHtml = `
<div class="hidden">
    <form class="row g-3 search-form">
        <div class="col-3">
            <label for="search_text">Search</label>
            <input class="form-control" name="text" id="search_text">
        </div>
        <div class="col-2">
            <label for="search_state">State</label>
            <select class="form-select" name="state" id="search_state">
                <option value="">-</option>
            </select>
        </div>
        <div class="col-2">
            <label for="search_reported_min">Reported min.</label>
            <input class="form-control" name="reported_min" type="date" id="search_reported_min">
        </div>
        <div class="col-2">
            <label for="search_reported_max">Reported max.</label>
            <input class="form-control" name="reported_max" type="date" id="search_reported_max">
        </div>
        <div class="col-2">
            <label for="search_employees_min">Employees min.</label>
            <input class="form-control" name="employees_min" type="number" id="search_employees_min">
        </div>
        <div class="col-1">
            <label for="search_clear"></label>
            <input type="submit" class="hidden">
            <button class="form-control clear-form btn btn-secondary" id="search_clear">Clear</button>
        </div>
    </form>
</div>`

async function initSearchTable(table, form, ...args) {
    const optsets = [
        defaults,
        {layout: {topStart: form}},
        getServerSideOpts(form),
        getStateSaveOpts(form),
    ]
    const opts = $.extend(true, {}, ...optsets, ...args)
    const dt = table.DataTable(opts)
    await initSearchForm(form, table)
    return dt
}

$(async () => {
    const main = $('#id_maincontent')
    const wrapper = $('<div/>')
    const table = $('<table/>')
        .addClass(['table', 'table-striped', 'responsive', 'reports-table'])
        appendTo(wrapper)
    const form = $(formHtml).appendTo(wrapper).find('form')
    await initSearchTable(table, form)
    main.append(wrapper)
    // const wrappers = $('.reports-auto-search').toArray()
    // for (const wrapper of wrappers) {
    //     const table = $('table', wrapper)
    //     const form = $(formHtml).appendTo(wrapper)
    //     await initSearchTable(table, form)
    // }
})
