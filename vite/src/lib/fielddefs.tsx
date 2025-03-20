import type { FieldDefs } from './models'
import type { ReportData } from '../lib/models'
export const reportFields: FieldDefs = {
  state: { title: 'State' },
  company: { title: 'Company' },
  reported: { title: 'Reported', type: 'date' },
  starting: { title: 'Starting', type: 'date' },
  employees: { title: 'Employees' },
  action: { title: 'Action', orderable: false },
  location: { title: 'Location' },
  url: { title: 'URL' },
}
export const reportSlots = {
  company: (data: any, type: string, row: ReportData) => {
    if (type === 'display') {
      return (<a href={`/r/${row.id}`}>{data}</a>)
    }
    return data
  }
}

const reports_count = { title: 'Reports Count' }
export const stateFields: FieldDefs = {
  id: { title: 'State' },
  reports_count,
  last_reported: { title: 'Last Reported' },
}

export const naicsFields: FieldDefs = {
  id: { title: 'ID' },
  title: { title: 'Title' },
  reports_count,
}