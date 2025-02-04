import {getFormParams} from './main.js'
import {populateStateSelects, ReportColumns, createTableComponent} from './table.js'


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

const defaultOrder = [{name: 'reported', dir: 'desc'}]

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
        dt.state({order: defaultOrder})
        clearTimeout(reqTimeout)
        doDraw()
    })
}
const formHtml = `
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
    </form>`

export async function renderPage(target) {
    const form = $(formHtml)
    await populateStateSelects(form)
    const defn = {
        id: 'reports_search',
        columns: ReportColumns,
        collection: 'reports',
        params: data => setSearchPayload(data, form),
    }
    const opts = {
        layout: {
            topEnd: null,
            bottomStart: 'pageLength',
            bottomEnd: 'paging',
            bottom2Start: 'info',
            topStart: form
        },
        pageLength: 25,
        autoWidth: false,
        order: defaultOrder,
        stateSave: true,
        stateSaveParams: (settings, data) => setStateSaveParams(data, form),
        stateLoadParams: (settings, data) => loadStateSaveParams(data, form),
    }
    const wrapper = createTableComponent(defn, opts)
    const table = $('table', wrapper)
    initSearchForm(form, table)
    $(target).html(wrapper)
}
