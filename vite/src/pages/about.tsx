import {naicsFields, stateFields} from '../lib/fielddefs'
import Datatable from '../components/Datatable'

export default function () {
  const opts = {
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
        columns={stateFields}
        options={opts} />
      <Datatable
        title='NAICS Stats'
        collection='naics'
        fixedParams={{
          reports_count_min: 1,
          depth_max: 0,
        }}
        columns={naicsFields}
        options={opts} />
    </div>
  )
}
