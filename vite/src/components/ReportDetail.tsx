import { reportFields, reportSlots } from '../lib/fielddefs'
import type { ReportData } from '../lib/models'

const fieldNames = [
  'state',
  'reported',
  'starting',
  'employees',
  'action',
  'location',
  'url',
]
function* rows(report: ReportData) {
  for (const name of fieldNames) {
    const { title } = reportFields[name]
    if (!report[name]) {
      continue
    }
    const render = reportSlots[name]
    const value = render
      ? render(report[name], 'display', report)
      : report[name]
    yield (
      <tr>
        <th scope='row'>{title}</th>
        <td>{value}</td>
      </tr>
    )
  }
}

export default function ({ report }: { report: ReportData }) {
  return (
    <div>
      <h2>{report.company}</h2>
      <table className='report-detail-table'>
        <tbody>
          {...Array.from(rows(report))}
        </tbody>
      </table>
    </div>
  )
}
