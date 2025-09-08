import * as bootstrap from 'bootstrap'
import DataTablesCore from 'datatables.net-bs5'
import type { DataTableRef } from 'datatables.net-react'
import DataTableBase from 'datatables.net-react'
import 'datatables.net-responsive-bs5'
import { Fields, Slots } from '../lib/fielddefs'
import type { ColDefs } from '../lib/models'
import { fetchok } from '../lib/utils'

// https://datatables.net/manual/react
DataTablesCore.use(bootstrap)
DataTableBase.use(DataTablesCore)

type FormRef = React.RefObject<HTMLFormElement>

interface TableProps {
  id?: string
  collection: string
  columns?: string[]
  coldefs?: ColDefs
  slots?: any
  title?: string | any
  options?: any
  fixedParams?: any
  searchFormRef?: FormRef
  className?: string
  ref?: React.RefObject<DataTableRef>
  onAjax?(res: any, rep: Response): void
}

export default function (
  {
    id,
    collection,
    coldefs,
    columns,
    slots,
    title,
    options,
    fixedParams,
    searchFormRef,
    className,
    ref,
    onAjax,
  }: TableProps
) {
  id = id || `id_${String(Math.random()).substring(2)}`
  coldefs = { ...Fields[collection], ...(coldefs || {}) }
  slots = { ...Slots[collection], ...(slots || {}) }
  columns = columns || Object.keys(coldefs)
  const classSet = new Set(['display', 'table', 'table-striped', 'responsive'])
  if (className) {
    for (let name of className.split(' ')) {
      name = name.trim()
      if (name.length) {
        classSet.add(name)
      }
    }
  }
  className = Array.from(classSet).sort().join(' ')
  const colspecs: any[] = columns.map(name => {
    const defn = coldefs[name]
    return { name, data: name, title: name, ...defn }
  })
  const head = typeof title === 'string'
    ? (<h2>{title}</h2>)
    : title
  options = {
    responsive: true,
    processing: true,
    serverSide: true,
    stateSaveCallback: (settings: any, data: any) => {
      localStorage.setItem(`dtstate_${id}`, JSON.stringify(data))
    },
    stateLoadCallback: () => {
      const json = localStorage.getItem(`dtstate_${id}`)
      if (!json) {
        return null
      }
      return JSON.parse(json)
    },
    ...(options || {}),
  }
  async function ajax(data: any, callback: Function, settings: any) {
    const path = `/api/v0/${collection}`
    const params = dtparams(data, searchFormRef, fixedParams)
    const uri = `${path}?${params}`
    const tasks = [
      fetchok(uri),
      getstats(),
    ]
    const stats = await tasks.pop()
    const rep = await tasks.pop() as Response
    const res = {
      data: await rep.json(),
      recordsFiltered: Number(rep.headers.get('count')),
      recordsTotal: stats.collections[collection].count,
      draw: data.draw,
    }
    callback(res)
    if (onAjax) {
      onAjax(res, rep)
    }
  }
  function onStateSaveParams(e: any, settings: any, data: any) {
    if (!searchFormRef) {
      return
    }
    const params = new URLSearchParams
    for (const [key, value] of getSearchFormData(searchFormRef)) {
      params.append(key, value)
    }
    Object.assign(data, Object.fromEntries(params.entries()))
  }
  function onStateLoadParams(e: any, settings: any, data: any) {
    if (!searchFormRef) {
      return
    }
    const form = searchFormRef.current
    for (const key of new FormData(form).keys()) {
      if (data[key]) {
        const el = form.querySelector(`[name="${key}"]`) as HTMLInputElement
        if (el) {
          el.value = data[key]
        }
      }
    }
  }
  return (
    <div>
      {head}
      <DataTableBase
        key={id}
        ref={ref}
        ajax={ajax}
        onStateSaveParams={onStateSaveParams}
        onStateLoadParams={onStateLoadParams}
        columns={colspecs}
        slots={slots}
        className={className}
        options={options}><></></DataTableBase>
    </div>
  )
}

async function getstats() {
  const rep = await fetchok('/api/v0/_db')
  return await rep.json()
}

const oparam = ({ name, dir }) => (
  (dir[0] === 'd' ? '-' : '') + name
)

function dtparams(data: any, searchFormRef?: FormRef, fixedParams?: any) {
  const params = new URLSearchParams({
    offset: data.start,
  })
  if (data.length >= 0) {
    params.set('limit', String(data.length))
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
  if (searchFormRef) {
    for (const [key, value] of getSearchFormData(searchFormRef)) {
      params.append(key, value)
    }
  }
  if (fixedParams) {
    for (const [key, value] of Object.entries(fixedParams)) {
      params.set(key, String(value))
    }
  }
  return params
}

function* getSearchFormData(formRef: FormRef) {
  if (!formRef) {
    return
  }
  const form = formRef.current
  if (!form) {
    return
  }
  const formData = new FormData(form)
  for (const [key, value] of formData.entries()) {
    const { length } = value as string
    if (key === 'text' && length < 2) {
      continue
    }
    if (length) {
      yield [key, String(value)]
    }
  }
}