import Datatable from '../components/Datatable'

export default function () {
  const options = {
    autoWidth: false,
    paging: false,
    filter: false,
    layout: {
      bottomStart: null,
    },
  }
  return (
    <div>
      <Datatable
        title='State Stats'
        collection='states'
        options={options} />
      <Datatable
        title='NAICS Stats'
        collection='naics'
        fixedParams={{
          reports_count_min: 1,
          depth_max: 0,
        }}
        options={options} />
    </div>
  )
}
