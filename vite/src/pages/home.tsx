import React from 'react'
import coldefs from '../lib/coldefs'
import { makedt } from '../lib/datatables'

export async function clientLoader() {
  // you can now fetch data here
  return {
    title: 'Home',
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
  fixedParams: {
    employees_min: 50,
    order: '-reported',
  },
  columns: coldefs.report,
  options: {
    pageLength: 10,
    ordering: false,
    lengthChange: false,
    filter: false,
    layout: {
      bottomStart: null,
    },
    autoWidth: false,
  },
}