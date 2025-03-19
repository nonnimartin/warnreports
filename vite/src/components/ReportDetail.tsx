import fielddefs from '../lib/fielddefs'
import type { FieldDefs, ReportData } from '../lib/models'

function row(title: string, content: any) {
  return (
    <tr>
      <th scope='row'>{title}</th>
      <td>{content}</td>
    </tr>
  )
}

function* rows(fields: FieldDefs, report: ReportData) {
  for (const [name, { title }] of Object.entries(fields)) {
    const value = report[name]
    yield row(title, value)
  }
}

export default function ({ report }: { report: ReportData }) {
  const fields = fielddefs.report
  return (
    <div>
      <h2>{report.company}</h2>
      <table className='report-detail-table'>
        <tbody>
          {...Array.from(rows(fields, report))}
        </tbody>
      </table>
    </div>
  )
}
