import 'https://cdn.datatables.net/2.1.8/js/dataTables.min.js'
import 'https://cdn.datatables.net/2.1.8/js/dataTables.bootstrap5.min.js'

import { aajax, cache, nf, strunc, renderDate, renderError } from './main.js'

export const ReportFieldRender = {
    company: (value, type, row) => $('<a/>')
        .attr({href: `/r/${row.id}`, title: value})
        .text(strunc(value, 50)),
    action: value => !value ? '' : $('<span/>')
        .attr({title: value})
        .text(strunc(value, 40)),
    url: value => !value ? '' : $('<a/>')
        .attr({href: value, target: '_blank'})
        .text(value),
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

export class TableComponent {

    constructor(defn) {
        defn = defn || {}
        this.id = defn.id || `id_${String(Math.random()).substring(2)}`
        this.opts = defn.opts || {}
        this.tableClasses = defn.tableClasses || ['table', 'table-striped', 'responsive']
        this.wrapperClasses = defn.wrapperClasses || []
        this.titleTag = defn.titleTag || 'h2'
        for (const key of ['url', 'title', 'columns', 'data', 'collection', 'params', 'searchForm']) {
            this[key] = defn[key]
        }
        this.wrapper = $('<div/>')
            .attr({id: this.id})
            .addClass(this.wrapperClasses)
        if (this.title) {
            this.heading = $(`<${this.titleTag}/>`)
                .text(this.title)
                .appendTo(this.wrapper)
        }
        this.table = $('<table/>')
            .attr({id: `${this.id}_table`})
            .addClass(this.tableClasses)
            .appendTo(this.wrapper)
    }

    async build() {
        this.dt = this.table.DataTable(await this.getTableOpts())
        return this.wrapper
    }

    async getTableOpts() {
        const opts = {...this.opts}
        opts.columns = []
        for (const c of this.columns) {
            const col = {...c}
            col.data = c.data || c.name
            if (c.name) {
                col.className = col.className || `field-${c.name}`
            }
            col.render = columnRenderer(c)
            opts.columns.push(col)
        }
        if (this.collection) {
            opts.ajax = async (data, callback, settings) => {
                const params = await this.getSearchParams(data)
                let rep
                try {
                    rep = await dtAjax(this.collection, params)
                } catch(e) {
                    const errHtml = await this.renderError(e)
                    callback({data: [], recordsFiltered: 0, recordsTotal: 0})
                    $('.dt-empty', this.table).html(errHtml)
                    return
                }
                callback(rep)
            }
            opts.processing = true
            opts.serverSide = true
        } else if (this.url) {
            opts.ajax = {dataSrc: this.data || '', url: this.url}
            const params = await this.getSearchParams({})
            const query = new URLSearchParams(params).toString()
            if (query) {
                opts.ajax.url += '?' + query
            }
        } else if (this.data) {
            if (typeof this.data === 'function') {
                opts.data = Array.from(await this.data())
            } else {
                opts.data = Array.from(this.data)
            }
        }
        return opts
    }

    async renderError(e) {
        return await await renderError(e)
    }

    async getSearchParams(params) {
        if (this.searchForm) {
            let formData = new FormData($(this.searchForm).get(0))
            const ret = await this.getSearchFormData(formData)
            if (ret) {
                formData = ret
            }
            if (formData) {
                params = {...params, ...plainObjParams(formData)}
            }
        }
        if (this.params) {
            if (typeof this.params === 'function') {
                const ret = await this.params(params)
                if (ret) {
                    params = plainObjParams(ret)
                }
                return params
            }
            params = {...params, ...plainObjParams(this.params)}
        }
        return params
    }

    getSearchFormData(formData) {
        formData = formData || new FormData($(this.searchForm).get(0))
        const params = new URLSearchParams
        for (const [field, value] of formData.entries()) {
            if (value.length) {
                params.append(field, value)
            }
        }
        return plainObjParams(params)
    }
}

function plainObjParams(params) {
    if (!params) {
        return {}
    }
    if ((params instanceof FormData) || (params instanceof URLSearchParams)) {
        return Object.fromEntries(params.entries())
    }
    return params
}

export async function populateStateSelects(form) {
    const stateOpt = id => $('<option/>').attr({value: id}).text(String(id))
    let states
    for (const select of $('select[name="state"]', form).toArray()) {
        states = states || await cache.fetch('states')
        for (const state of states) {
            stateOpt(state.id).appendTo(select)
        }
    }
}

const columnRenderer = c => {
    let {render, type} = c
    if (!render) {
        if (type === 'num') {
            return nf
        }
        if (type === 'date') {
            return renderDate
        }
        return
    }
    return (...args) => {
        const value = render(...args)
        return typeof value === 'object'
            ? value.get(0).outerHTML
            : value
    }
}

async function dtAjax(collection, params) {
    params = cleanDtParams(params)
    const {draw} = params
    delete params.draw
    const opts = {url: `/api/v0/${collection}`, method: 'GET', data: params}
    const {body, xhr} = await aajax(opts)
    const stats = await cache.fetch('stats')
    return {
        data: body,
        recordsFiltered: +xhr.getResponseHeader('count'),
        recordsTotal: stats.collections[collection].count,
        draw,
        xhr,
    }
}

function cleanDtParams(params) {
    params = {...params}
    params.limit = params.length
    if (+params.limit < 0) {
        delete params.limit
    }
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
