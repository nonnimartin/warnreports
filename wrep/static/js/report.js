import {aajax} from './main.js'
import { ReportColumns, createTableComponent } from './table.js'

$(async () => {
    const main = $('#id_maincontent')
    const reportId = window.location.pathname.split('/').pop()
    const report = (await aajax({url: `/api/v0/reports/${reportId}`})).body
    const {company_id} = report
    const defn = {
        id: 'related_reports',
        title: 'Related',
        url: '/api/v0/reports',
        params: {id_not: reportId, company_id, order: '-reported'},
        columns: ReportColumns,
    }
    const opts = {
        order: [{name: 'reported', dir: 'desc'}],
        pageLength: 25,
        autoWidth: false,
    }
    const wrapper = createTableComponent(defn, opts)
    wrapper.addClass(['slim', 'hide-empty', 'hidden'])
    main.append(wrapper)
})