import {getFormParams} from './main.js'
import {populateStateSelects, ReportColumns, createTableComponent} from './table.js'

function updateForm(form) {
    const params = new URLSearchParams(window.location.search)
    for (const name of params.keys()) {
        $(`:input[name="${name}"]`, form).val(params.getAll(name).join(','))
    }
}

function updateFeedInfo(feedInfo, id) {
    if (id) {
        const description = paramsToDesc(idToParams(id))
        feedInfo.html([
            '<dt>Feed Title</dt>',
            $('<dd/>').text(`WARN Reports ${description}`),
            '<dt>Permalinks</dt>',
            $('<dd/>').append([
                $('<a/>').attr({href: `/feed/rss/${id}`}).text('RSS'),
                '<span> | </span>',
                $('<a/>').attr({href: `/feed/atom/${id}`}).text('Atom'),
            ])
        ])
    } else {
        feedInfo.html('')
    }
}

function idToParams(id) {
    return new URLSearchParams(atob(id.replace('-', '+').replace('_', '/')))
}

function paramsToDesc(params) {
    const p = new URLSearchParams(params)
    const descs = []
    if (p.has('state')) {
        descs.push(p.getAll('state').join(','))
        p.delete('state')
    }
    if (p.has('employees_min')) {
        descs.push(p.get('employees_min') + '+')
        p.delete('employees_min')
    }
    if (p.has('naics')) {
        descs.push('NAICS=' + p.getAll('naics').join(','))
        p.delete('naics')
    }
    if (p.has('text')) {
        descs.push(p.get('text'))
        p.delete('text')
    }
    for (const item of p.toString().split('&')) {
        if (item) {
            descs.push(item)
        }
    }
    return descs.join(' ')
}

const staticHtml = 
`<div>
    <h2>Full Feed</h2>
    <ul>
        <li><a href="/feed/rss">RSS</a></li>
        <li><a href="/feed/atom">Atom</a></li>
    </ul>
    <h2>Custom Feed</h2>
    <form class="row g-3" id="search_form">
        <div class="col-4">
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
            <label for="search_employees_min">Employees</label>
            <input class="form-control" name="employees_min" type="number" id="search_employees_min">
        </div>
        <div class="col-2">
            <label for="search_naics">NAICS</label>
            <input class="form-control" name="naics" type="number" id="search_naics">
        </div>
        <div class="col-1">
            <label for="search_submit"></label>
            <button type="submit" class="form-control btn btn-primary" id="search_submit">Submit</button>
        </div>
        <div class="col-1">
            <label for="search_clear"></label>
            <button class="form-control form-reset btn btn-secondary" id="search_clear">Clear</button>
        </div>
    </form>
</div>`

const fixedParams = {
    order: '-reported',
    limit: 50,
    offset: 0,
}
const opts = {
    paging: false,
    ordering: false,
    lengthChange: false,
    filter: false,
    layout: {
        bottomStart: null
    },
}

function handleSubmit(e) {
    e.preventDefault()
    const params = getFormParams(this)
    for (const key of params.keys()) {
        params.set(key, params.getAll(key).join(','))
    }
    const search = params.size ? `?${params.toString()}` : ''
    if (search !== window.location.search) {
        const href = `${window.location.pathname}${search}`
        window.location.href = href
    }
}

function handleResetClick(e) {
    e.preventDefault()
    if (window.location.search) {
        window.location.href = window.location.pathname
    } else {
        $(this).closest('form').get(0).reset()
    }
}

export async function renderPage(target) {
    const staticDiv = $(staticHtml)
    const form = $('form', staticDiv)
    await populateStateSelects(form)
    updateForm(form)
    const params = getFormParams(form)
    for (const entry of Object.entries(fixedParams)) {
        params.set(...entry)
    }
    const defn = {
        id: 'feed_table',
        columns: ReportColumns,
        url: '/api/v0/reports',
        params,
    }
    form.on('submit', handleSubmit)
    $('.form-reset', form).on('click', handleResetClick)
    const feedInfo = $('<dl/>')
    const wrapper = createTableComponent(defn, opts)
    const table = $('table', wrapper)
    table.DataTable().on('xhr', (e, settings, json, xhr) => {
        updateFeedInfo(feedInfo, xhr.getResponseHeader('feed-id'))
    })
    $(target).empty().append([staticDiv, feedInfo, wrapper])
}
