import type { ReportData } from '../lib/models'
import coldefs from '../lib/coldefs'
import Datatable from './Datatable'

export default function ({ report }: { report: ReportData }) {
  const opts = {
    autoWidth: false,
    pageLength: 10,
    ordering: false,
    lengthChange: false,
    filter: false,
    layout: {
      bottomStart: null
    },
  }
  return (
    <Datatable
      title='Related'
      collection='reports'
      columns={coldefs.reports}
      options={opts}
      fixedParams={{
        company_id: report.company_id,
        id_not: report.id,
        order: '-reported',
      }} />
  )
}