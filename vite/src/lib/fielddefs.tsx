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
  url: { title: 'URL', orderable: false },
}

export const reportSlots = {
  company: (data: any, type: string, row: ReportData) => {
    if (type === 'display') {
      return (<a href={`/r/${row.id}`}>{data}</a>)
    }
    return data
  },
  url: (data: any, type: string, row: ReportData) => {
    if (type === 'display') {
      return (<a href={data} target="_blank">{data}</a>)
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
export const stateSlots = {}

export const naicsFields: FieldDefs = {
  id: { title: 'ID' },
  title: { title: 'Title' },
  reports_count,
}
export const naicsSlots = {}

export const Fields = {
  reports: reportFields,
  states: stateFields,
  naics: naicsFields,
}

export const Slots = {
  reports: reportSlots,
  states: stateSlots,
  naics: naicsSlots,
}