import Datatable from '../components/Datatable'

export default function () {
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
      bottomStart: null,
    },
  }
  const fixedParams = {
    employees_min: 50,
    order: '-reported',
  }
  return (
    <Datatable
      title='Recent 50+ employees'
      collection='reports'
      columns={columns}
      options={options}
      fixedParams={fixedParams} />
  )
}
