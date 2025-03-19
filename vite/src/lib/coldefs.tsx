export const reports = {
  state: { title: 'State' },
  company: { title: 'Company' },
  reported: { title: 'Reported', type: 'date' },
  starting: { title: 'Starting', type: 'date' },
  employees: { title: 'Employees', type: 'num' },
  action: { title: 'Action', orderable: false },
}
const reports_count = { title: 'Reports Count' }
export const states = {
  id: { title: 'State' },
  reports_count,
  last_reported: { title: 'Last Reported' },
}
export const naics = {
  id: { title: 'ID' },
  title: { title: 'Title' },
  reports_count,
}
export default { reports, states, naics }