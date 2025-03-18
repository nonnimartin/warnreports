import React from 'react'
import coldefs from '../lib/coldefs'
import { makedt } from '../lib/datatables'

export async function clientLoader() {
  // you can now fetch data here
  return {
    title: 'About',
  }
}

export default function Component({ loaderData }) {
  return (
    <div>
      <h1>{loaderData.title}</h1>
      {makedt(tableConfigs.states)}
    </div>
  )
}

const tableConfigs = {
  states: {
    collection: 'states',
    columns: coldefs.state,
    options: {
      // pageLength: 10,
      paging: false,
      // ordering: false,
      lengthChange: false,
      filter: false,
      layout: {
        bottomStart: null,
      },
      autoWidth: false,
    },
  },
}