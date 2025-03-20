import {reportFields, reportSlots as slots} from '../lib/fielddefs'
import Datatable from '../components/Datatable'

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
  const options = {
    autoWidth: false,
    pageLength: 10,
    ordering: false,
    lengthChange: false,
    filter: false,
    layout: {
      bottomStart: null,
    },
  }
  return (
    <Datatable
      title='Recent 50+ employees'
      collection='reports'
      columns={columns}
      options={options}
      slots={slots}
      fixedParams={{
        employees_min: 50,
        order: '-reported',
      }}
      />
  )
}
