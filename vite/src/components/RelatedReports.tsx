import {reportFields} from '../lib/fielddefs'
import type { ReportData } from '../lib/models'
import Datatable from './Datatable'

const colNames = [
  'state',
  'company',
  'reported',
  'starting',
  'employees',
  'action',
]
const columns = Object.fromEntries(
  colNames.map(key => ([key, reportFields[key]]))
)
const slots = {
  company: (data: any, type: string, row: ReportData) => {
    if (type === 'display') {
      return (<a href={`/r/${row.id}`}>{data}</a>)
    }
    return data
  }
}

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
      columns={columns}
      options={opts}
      slots={slots}
      fixedParams={{
        company_id: report.company_id,
        id_not: report.id,
        order: '-reported',
      }} />
  )
}