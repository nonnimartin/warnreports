import { aajax, escapeHtml, renderError } from './main.js'
import { createTableComponent, ReportColumns, ReportFieldRender } from './table.js'

class ReportDetail {

    constructor(reportId) {
        this.reportId = reportId
    }

    async fetch() {
        const url = `/api/v0/reports/${this.reportId}`
        this.report = (await aajax({url})).body
    }

    async render() {
        const renders = [
            this.renderDetail(),
            this.renderArtifacts(),
            this.renderNaics(),
            this.renderRelatedTable(),
        ]
        const wrapper = $('<div class="report-view"/>')
        for (const prom of renders) {
            const content = await prom
            if (content) {
                wrapper.append(content)
            }
        }
        return wrapper
    }

    async renderDetail() {
        const {report} = this
        const table = $('<table class="report-detail-table"/>')
        const tbody = $('<tbody/>').appendTo(table)
        const row = (label, content) => {
            const tr = $('<tr/>').appendTo(tbody)
            $('<th scope="row"/>').appendTo(tr).text(label)
            $('<td/>').appendTo(tr).html(content)
        }
        const fielddefs = [
            ['State', 'state'],
            ['Reported', 'reported'],
            ['Starting', 'starting'],
            ['Employees', 'employees'],
            ['Action', 'action'],
            ['Location', 'location'],
            ['URL', 'url'],
        ]
        const renderers = {...ReportFieldRender}
        for (const [label, name] of fielddefs) {
            let value = report[name]
            if (!value) {
                continue
            }
            const render = renderers[name] || escapeHtml
            row(label, render(value))
        }
        return $('<div class="report-detail"/>').append([
            $('<h2/>').text(report.company),
            table,
        ])
    }

    async renderArtifacts() {
        const {artifacts} = this.report
        if (!artifacts.length) {
            return ''
        }
        const table = $('<table/>')
        const tbody = $('<tbody/>').appendTo(table)
        const link = (id, disposition) => $('<a/>')
            .attr({
                href: `/api/v0/artifacts/${id}/data?disposition=${disposition}`,
                target: '_blank',
            })
        const row = ({id, name}) => {
            $('<tr/>').appendTo(tbody).append([
                $('<td/>').append(link(id, 'inline').text(name)),
                $('<td/>').append(link(id, 'download').text('download')),
            ])
        }
        for (const artifact of artifacts) {
            row(artifact)
        }
        return $('<div class="report-artifacts"/>').append([
            '<h3>Artifacts</h3',
            table,
        ])
    }

    async renderNaics() {
        const {naics} = this.report
        if (!naics.length) {
            return ''
        }
        const table = $('<table/>')
        const tbody = $('<tbody/>').appendTo(table)
        const row = ({id, depth, title}) => {
            $('<tr/>').appendTo(tbody).append([
                $('<td/>').text(id),
                $(`<td class="naics-depth-${depth}"/>`).text(title),
            ])
        }
        for (const naic of naics) {
            row(naic)
        }
        return $('<div class="report-naics"/>').append([
            '<h3>NAICS</h3',
            table,
        ])
    }

    async renderRelatedTable() {
        const {id, company_id} = this.report
        const defn = {
            id: 'related_reports',
            title: 'Related',
            collection: 'reports',
            columns: ReportColumns,
            params: {company_id, id_not: id, order: '-reported'},
        }
        const opts = {
            pageLength: 10,
            ordering: false,
            lengthChange: false,
            filter: false,
            layout: {
                bottomStart: null
            },
        }
        return createTableComponent(defn, opts).addClass(['hide-empty', 'hidden'])
    }
}
export async function renderPage(target) {
    const reportId = window.location.pathname.split('/').pop()
    const detail = new ReportDetail(reportId)
    try {
        await detail.fetch()
    } catch(e) {
        $(target).html(await renderError(e))
        return
    }
    $(target).html(await detail.render())
}
