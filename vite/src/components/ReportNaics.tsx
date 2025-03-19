import type { Naic, ReportData } from '../lib/models'

export default function ({ report }: { report: ReportData }) {
  const {naics} = report
  if (!naics.length) {
    return
  }
  return (
    <div className='report-naics'>
      <h3>NAICS</h3>
      <table>
        <tbody>
          {...naics.map(row)}
        </tbody>
      </table>
    </div>
  )
}
function row({ id, depth, title }: Naic) {
  return (
    <tr>
      <td>{id}</td>
      <td className={`naics-depth-${depth}`}>{title}</td>
    </tr>
  )
}