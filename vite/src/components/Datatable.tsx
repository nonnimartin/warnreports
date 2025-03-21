import type { ColDefs } from '../lib/models'
import { Fields, Slots } from '../lib/fielddefs'
import { fetchok } from '../lib/utils'
import * as bootstrap from 'bootstrap'
import DataTableBase from 'datatables.net-react'
import DataTablesCore from 'datatables.net-bs5'
import 'datatables.net-responsive-bs5'

interface TableProps {
  collection: string
  columns?: string[]
  coldefs?: ColDefs
  slots?: any
  title?: string|any
  options?: any
  fixedParams?: any
  searchForm?: any
}

export default function (
  {
    collection,
    coldefs,
    columns,
    title,
    options,
    fixedParams,
    searchForm,
    slots,
  }: TableProps
) {
  coldefs = {...Fields[collection], ...(coldefs || {})}
  slots = {...Slots[collection], ...(slots || {})}
  columns = columns || Object.keys(coldefs)
  const classes = ['display', 'table', 'table-striped', 'responsive']
  const colspecs: any[] = columns.map(name => {
    const defn = coldefs[name]
    return {name, data: name, title: name, ...defn}
  })
  options = {
    responsive: true,
    processing: true,
    serverSide: true,
    ...(options || {}),
  }
  return (
    <div>
      {searchForm}
      {typeof title === 'string' ? <h2>{title}</h2> : title}
      <DataTableBase
        ajax={dtajax(collection, fixedParams)}
        columns={colspecs}
        slots={slots}
        className={classes.join(' ')}
        options={options}><></></DataTableBase>
    </div> 
  )
}

// https://datatables.net/manual/react
DataTablesCore.use(bootstrap)
DataTableBase.use(DataTablesCore)

function dtajax(collection: string, fixedParams?: any) {
  return async (data: any, callback: Function, settings: any) => {
    const path = `/api/v0/${collection}`
    const params = dtparams(data, fixedParams)
    const uri = `${path}?${params}`
    const tasks = [
      fetchok(uri),
      getstats(),
    ]
    const stats = await tasks.pop()
    const rep = await tasks.pop()
    callback({
      data: await rep.json(),
      recordsFiltered: Number(rep.headers.get('count')),
      recordsTotal: stats.collections[collection].count,
      draw: data.draw,
    })
  }
}

async function getstats() {
  const rep = await fetchok('/api/v0/_db')
  return await rep.json()
}

const oparam = ({ name, dir }) => (
  (dir[0] === 'd' ? '-' : '') + name
)

function dtparams(data: any, fixedParams?: any) {
  const params = new URLSearchParams({
    offset: data.start,
  })
  if (data.length >= 0) {
    params.set('limit', data.length)
  }
  const optional = {
    order: data.order.map(oparam).join(','),
    text: data.search?.value,
  }
  for (const [key, value] of Object.entries(optional)) {
    if (value) {
      params.set(key, value)
    }
  }
  if (fixedParams) {
    for (const [key, value] of Object.entries(fixedParams)) {
      params.set(key, String(value))
    }
  }
  return params
}
