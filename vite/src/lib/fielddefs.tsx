import coldefs from './coldefs'
import type { FieldDefs } from './models'
export const report: FieldDefs = {
  ...coldefs.reports,
  location: { title: 'Location' },
  url: { title: 'URL' },
}
delete report.company
export default { report }