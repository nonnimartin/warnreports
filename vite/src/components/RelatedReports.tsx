import type { ReportData } from '../lib/models'
import Datatable from './Datatable'

export default function ({ report }: { report: ReportData }) {
  const columns = [
    'state',
    'company',
    'reported',
    'starting',
    'employees',
    'action',
  ]
  const options = {
    autoWidth: false,
    pageLength: 10,
    ordering: false,
    lengthChange: false,
    filter: false,
    layout: {
      bottomStart: null
    },
  }
  const fixedParams = {
    company_id: report.company_id,
    id_not: report.id,
    order: '-reported',
  }
  return (
    <Datatable
      title='Related'
      collection='reports'
      columns={columns}
      options={options}
      fixedParams={fixedParams} />
  )
}