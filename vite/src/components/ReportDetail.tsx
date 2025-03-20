import {reportFields} from '../lib/fielddefs'
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
    const {title} = reportFields[name]
    const value = report[name]
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
