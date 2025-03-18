import React from 'react'
import * as bootstrap from 'bootstrap'
import DataTable from 'datatables.net-react'
import DataTablesCore from 'datatables.net-bs5'

import './index.css'
import './App.css'

// https://datatables.net/manual/react
DataTablesCore.use(bootstrap)
DataTable.use(DataTablesCore)

async function fetchok(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const rep = await fetch(input, init)
  if (rep.ok) {
    return rep
  }
  const msg = `${rep.status} for ${rep.url}`
  console.error(msg, {rep})
  throw new Error(msg)
}

function makedt(opts: any) {
  const {collection, columns, options} = opts
  function dtcolumns(defns: {[name: string]: {}}) {
    return Object.entries(defns).map(([name, defn]) => (
      {name, data: name, title: name, ...defn}
    ))
  }

  async function getstats() {
    const rep = await fetchok('/api/v0/_db')
    return await rep.json()
  }

  const oparam = ({name, dir}) => (
    (dir[0] === 'd' ? '-' : '') + name
  )

  function dtparams(data: any) {
    const params = new URLSearchParams({
      limit: data.length,
      offset: data.start,
    })
    const optional = {
      order: data.order.map(oparam).join(','),
      text: data.search?.value,
    }
    for (const [key, value] of Object.entries(optional)) {
      if (value) {
        params.set(key, value)
      }
    }
    return params
  }

  function dtajax(collection: string) {
    return async (data: any, callback: Function, settings: any) => {
      const stats = await getstats()
      const path = `/api/v0/${collection}`
      const params = dtparams(data)
      const uri = `${path}?${params}`
      console.log({data})
      const rep = await fetchok(uri)
      callback({
        data: await rep.json(),
        recordsFiltered: Number(rep.headers.get('count')),
        recordsTotal: stats.collections[collection].count,
        draw: data.draw,
      })
    }
  }

  return (
    <DataTable
      ajax={dtajax(collection)}
      columns={dtcolumns(columns)}
      className='display'
      options={{
        serverSide: true,
        processing: true,
        ...(options || {})
      }}
      ><></></DataTable>
  )
}

const dtconfigs = {
  states: {
    collection: 'states',
    columns: {
      id: {title: 'State'},
      reports_count: {title: 'Reports Count'},
    },
  },
  reportSearch: {
    collection: 'reports',
    columns: {
      state: {title: 'State'},
      company: {title: 'Company'},
      reported: {title: 'Reported', type: 'date'},
      starting: {title: 'Starting', type: 'date'},
      employees: {title: 'Employees', type: 'num'},
      action: {title: 'Action', orderable: false},
    },
    options: {
      order: {name: 'reported', dir: 'desc'},
      pageLength: 25,
      autoWidth: false,
    },
  },
}

function App() {
  return makedt(dtconfigs.reportSearch)
}

export default App