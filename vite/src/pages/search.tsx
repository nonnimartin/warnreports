import React from 'react'
import coldefs from '../lib/coldefs'
import { makedt } from '../lib/datatables'

export async function clientLoader() {
  // you can now fetch data here
  return {
    title: 'Search',
  }
}

export default function Component({ loaderData }) {
  return (
    <div>
      <h1>{loaderData.title}</h1>
      {makedt(tableConfig)}
    </div>
  )
}

const tableConfig = {
  collection: 'reports',
  columns: coldefs.report,
  options: {
    order: {name: 'reported', dir: 'desc'},
    pageLength: 25,
    autoWidth: false,
  },
}