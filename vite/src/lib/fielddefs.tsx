import type { FieldDefs } from './models'
import type { ReportData } from '../lib/models'
import { renderDate, strunc } from './utils'

const nformatter = new Intl.NumberFormat()

function dateSlot(data: any, type: string, row: any) {
  if (type === 'display' || type === 'detail') {
    return renderDate(data)
  }
  return data
}

function numSlot(data: any, type: string, row: any) {
  if (type === 'display' || type === 'detail') {
    return data == null
      ? ''
      : nformatter.format(data)
  }
  if (type === 'type') {
    return 1
  }
  if (type === 'sort') {
    return data || 0
  }
  return data
}

const reports_count = { title: 'Reports Count', type: 'num' }

export const Fields: {[x: string]: FieldDefs} = {
  reports: {
    state: { title: 'State', type: 'string' },
    company: { title: 'Company', type: 'string' },
    reported: { title: 'Reported', type: 'date' },
    starting: { title: 'Starting', type: 'date' },
    employees: { title: 'Employees', type: 'num' },
    action: { title: 'Action', type: 'string', orderable: false },
    location: { title: 'Location', type: 'string' },
    url: { title: 'URL', type: 'string', orderable: false },
  },
  states: {
    id: { title: 'State', type: 'string' },
    reports_count,
    last_reported: { title: 'Last Reported', type: 'date' },
  },
  naics: {
    id: { title: 'ID', type: 'num' },
    title: { title: 'Title', type: 'string' },
    reports_count,
  },
}

export const Slots = {
  reports: {
    company: (data: any, type: string, row: ReportData) => {
      if (type === 'display') {
        return (
          <span title={data}>
            <a href={`/r/${row.id}`}>{strunc(data, 50)}</a>
          </span>
        )
      }
      return data
    },
    reported: dateSlot,
    starting: dateSlot,
    employees: numSlot,
    action: (data: any, type: string, row: ReportData) => {
      if (type === 'display') {
        return data
          ? (<span title={data}>{strunc(data, 40)}</span>)
          : ''
      }
      return data
    },
    url: (data: any, type: string, row: ReportData) => {
      if (type === 'display' || type === 'detail') {
        return data
          ? (<a href={data} target="_blank">{data}</a>)
          : ''
      }
      return data
    }
  },
  states: {
    reports_count: numSlot,
    last_reported: dateSlot,
  },
  naics: {
    reports_count: numSlot,
  },
}
