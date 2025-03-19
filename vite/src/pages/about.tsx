import React from 'react'
import coldefs from '../lib/coldefs'
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
        columns={coldefs.states}
        options={opts} />
      <Datatable
        title='NAICS Stats'
        collection='naics'
        fixedParams={{
          reports_count_min: 1,
          depth_max: 0,
        }}
        columns={coldefs.naics}
        options={opts} />
    </div>
  )
}
