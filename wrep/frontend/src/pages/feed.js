import { renderError } from '../lib/main.js'
import { populateStateSelects, ReportColumns, TableComponent } from '../lib/table.js'


class FeedComponent {

    constructor() {
        this.handleSubmit = this.handleSubmit.bind(this)
        this.handleResetClick = this.handleResetClick.bind(this)
        this.wrapper = $(`
            <div>
                <h2>Full Feed</h2>
                <dl>
                    <dt>RSS</dt>
                    <dd><a href="/feed/rss">/feed/rss</a></dd>
                    <dt>Atom</dt>
                    <dd><a href="/feed/atom">/feed/atom</a></dd>
                </dl>
                <h2>Custom Feed</h2>
            </div>
        `)
        this.form = $(`
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
        `).appendTo(this.wrapper)
        this.feedInfo = $('<dl/>').appendTo(this.wrapper)
        this.form.on('submit', this.handleSubmit)
        $('.form-reset', this.form).on('click', this.handleResetClick)
        this.tableComponent = new TableComponent({
            id: 'feed_table',
            columns: ReportColumns,
            collection: 'reports',
            searchForm: this.form,
            params: {
                order: '-reported',
                limit: 50,
                offset: 0,
            },
            opts: {
                paging: false,
                ordering: false,
                lengthChange: false,
                filter: false,
                layout: {
                    bottomStart: null,
                },
                autoWidth: false,
            },
        })
        this.tableComponent.table.on('xhr.dt', async (e, settings, json) => {
            try {
                const {xhr} = json
                this.feedId = xhr.getResponseHeader('feed-id') || ''
                this.updateFeedInfo()
            } catch(e) {
                console.error(e)
                this.feedInfo.html(await renderError(e))
            }
        })
    }

    async build() {
        await populateStateSelects(this.form)
        const params = new URLSearchParams(window.location.search)
        const formData = new FormData(this.form.get(0))
        for (const name of formData.keys()) {
            if (params.has(name)) {
                $(`:input[name="${name}"]`, this.form).val(params.getAll(name).join(','))
            }
        }
        this.wrapper.append(await this.tableComponent.build())
        return this.wrapper
    }

    handleSubmit(e) {
        e.preventDefault()
        const formData = new FormData(this.form.get(0))
        const params = new URLSearchParams(
            this.tableComponent.getSearchFormData(formData)
        )
        const search = params.size ? `?${params.toString()}` : ''
        if (search !== window.location.search) {
            const href = `${window.location.pathname}${search}`
            window.location.href = href
        }
    }

    handleResetClick(e) {
        e.preventDefault()
        if (window.location.search) {
            window.location.href = window.location.pathname
        } else {
            this.form.get(0).reset()
        }
    }

    updateFeedInfo() {
        if (!this.feedId) {
            this.feedInfo.html('')
            return
        }
        const description = feedDescription(this.feedId)
        const atom = `/feed/atom/${this.feedId}`
        const rss = `/feed/rss/${this.feedId}`
        this.feedInfo.html([
            '<dt>Description</dt>',
            $('<dd/>').text(`WARN Reports ${description}`),
            '<dt>RSS</dt>',
            $('<dd/>').append($('<a/>').attr({href: rss}).text(rss)),
            '<dt>Atom</dt>',
            $('<dd/>').append($('<a/>').attr({href: atom}).text(atom)),
        ])
    }
}

function feedDescription(feedId) {
    const p = new URLSearchParams(decodeFeedId(feedId))
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

function decodeFeedId(feedId) {
    feedId = feedId || ''
    return new URLSearchParams(atob(feedId.replace('-', '+').replace('_', '/')))
}

export default new FeedComponent
