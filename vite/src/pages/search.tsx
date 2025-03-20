import {reportFields, reportSlots} from '../lib/fielddefs'
import Datatable from '../components/Datatable'
import SearchForm from '../components/SearchForm'

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

export default function () {
  const defaultOrder = [{ name: 'reported', dir: 'desc' }]
  const searchForm = (<SearchForm />)
  const options = {
    order: defaultOrder,
    pageLength: 25,
    autoWidth: false,
    layout: {
      topEnd: null,
      bottomStart: 'pageLength',
      bottomEnd: 'paging',
      bottom2Start: 'info',
      topStart: null,
    },
  }
  return (
    <Datatable
      collection='reports'
      columns={columns}
      searchForm={searchForm}
      options={options}
      slots={reportSlots} />
  )
}
