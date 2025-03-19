import type { Artifact, ReportData } from '../lib/models'

export default function ({ report }: { report: ReportData }) {
  const { artifacts } = report
  if (!artifacts.length) {
    return
  }
  return (
    <div className='report-naics'>
      <h3>Artifacts</h3>
      <table>
        <tbody>
          {...artifacts.map(row)}
        </tbody>
      </table>
    </div>
  )
}
function row({ id, name }: Artifact) {
  return (
    <tr>
      <td>{name}</td>
      <td>download</td>
    </tr>
  )
}