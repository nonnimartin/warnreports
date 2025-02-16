import { populateNaicsRootSelects, populateStateSelects, ReportColumns, TableComponent } from '../lib/table.js'


class SearchTableComponent extends TableComponent {

    constructor() {
        const searchForm = $(`
            <form class="row g-3 search-form">
                <div class="col-3">
                    <label for="search_text">Search</label>
                    <input class="form-control" name="text" id="search_text">
                </div>
                <div class="col-1">
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
                <div class="col-1">
                    <label for="search_employees_min">Emps. min.</label>
                    <input class="form-control" name="employees_min" type="number" id="search_employees_min">
                </div>
                <div class="col-2">
                    <label for="search_naics">Industry</label>
                    <select class="form-select" name="naics" id="search_naics">
                        <option value="">-</option>
                    </select>
                </div>
                <div class="col-1">
                    <label for="search_clear"></label>
                    <input type="submit" class="hidden">
                    <button class="form-control clear-form btn btn-secondary" id="search_clear">Clear</button>
                </div>
            </form>
        `)
        const defaultOrder = [{name: 'reported', dir: 'desc'}]
        super({
            id: 'reports_search',
            columns: ReportColumns,
            collection: 'reports',
            searchForm,
            opts: {
                layout: {
                    topEnd: null,
                    bottomStart: 'pageLength',
                    bottomEnd: 'paging',
                    bottom2Start: 'info',
                    topStart: searchForm,
                },
                pageLength: 25,
                autoWidth: false,
                order: defaultOrder,
                stateSave: true,
                stateSaveParams: (...args) => this.setStateSaveParams(...args),
                stateLoadParams: (...args) => this.loadStateSaveParams(...args),
            },
        })
        this.reqTimeout = null
        this.redrawDelay = 100
        this.defaultOrder = [{name: 'reported', dir: 'desc'}]
        this.handleSubmit = this.handleSubmit.bind(this)
        this.handleResetClick = this.handleResetClick.bind(this)
        this.handleFormChange = this.handleFormChange.bind(this)
        this.handleFormKeyupKeydown = this.handleFormKeyupKeydown.bind(this)
        this.searchForm.on('submit', this.handleSubmit)
        this.searchForm.on('change', this.handleFormChange)
        this.searchForm.on('keyup keydown', this.handleFormKeyupKeydown)
        $('.clear-form', this.searchForm).on('click', this.handleResetClick)
    }

    getSearchFormData(formData) {
        formData = formData || new FormData($(this.searchForm).get(0))
        if (formData.has('text') && formData.get('text').length < 2) {
            formData.delete('text')
        }
        return super.getSearchFormData(formData)
    }

    async build() {
        const tasks = [
            populateStateSelects(this.searchForm),
            populateNaicsRootSelects(this.searchForm),
        ]
        for (const task of tasks) {
            await task
        }
        return await super.build()
    }

    setStateSaveParams(settings, data) {
        const params = new URLSearchParams(this.getSearchFormData())
        Object.assign(data, Object.fromEntries(params.entries()))
    }

    loadStateSaveParams(settings, data) {
        for (const key of new FormData($(this.searchForm).get(0)).keys()) {
            if (data[key]) {
                $(`:input[name="${key}"]`, this.searchForm).val(data[key])
            }
        }
    }

    handleSubmit(e) {
        e.preventDefault()
        this.queueDraw()
    }

    handleResetClick(e) {
        e.preventDefault()
        $(':input', this.searchForm).val('')
        this.dt.state({order: this.defaultOrder})
        clearTimeout(this.reqTimeout)
        this.hash = new URLSearchParams(this.getSearchFormData()).toString()
        this.dt.draw()
    }

    handleFormChange(e) {
        this.queueDraw()
    }

    handleFormKeyupKeydown(e) {
        this.queueDraw()
    }

    queueDraw() {
        clearTimeout(this.reqTimeout)
        const hash = new URLSearchParams(this.getSearchFormData()).toString()
        if (this.hash !== hash) {
            this.reqTimeout = setTimeout(() => {
                this.hash = hash
                this.dt.draw()
            }, this.redrawDelay)
        }
    }
}

export default new SearchTableComponent
