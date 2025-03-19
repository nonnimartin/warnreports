import React from 'react'
import coldefs from '../lib/coldefs'
import Datatable from '../components/Datatable'

export default function () {
  const opts = {
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
      fixedParams={{
        employees_min: 50,
        order: '-reported',
      }}
      columns={coldefs.reports}
      options={opts} />
  )
}
