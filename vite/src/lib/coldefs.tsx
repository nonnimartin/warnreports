export const report = {
  state: { title: 'State' },
  company: { title: 'Company' },
  reported: { title: 'Reported', type: 'date' },
  starting: { title: 'Starting', type: 'date' },
  employees: { title: 'Employees', type: 'num' },
  action: { title: 'Action', orderable: false },
}
export const state = {
  id: { title: 'State' },
  reports_count: { title: 'Reports Count' },
}
export default { report, state }