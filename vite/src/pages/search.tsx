import { useRef } from 'react'
import Datatable from '../components/Datatable'
import SearchForm from '../components/SearchForm'
import { fetchok } from '../lib/utils'
import type { DataTableRef } from 'datatables.net-react'

export async function clientLoader() {
  const tasks = [
    fetchok(`/api/v0/states`),
    fetchok(`/api/v0/naics?depth_max=0`),
  ]
  const states: any[] = await (await tasks[0]).json()
  const naics: any[] = await (await tasks[1]).json()
  return { states, naics }
}

export default function ({ loaderData }) {
  const formId = 'id_search_form'
  const formRef = useRef<HTMLFormElement>(null)
  const table = useRef<DataTableRef>(null)
  const columns = [
    'state',
    'company',
    'reported',
    'starting',
    'employees',
    'action',
  ]
  const defaultOrder = [['reported', 'desc']]
  const options = {
    order: [{ name: 'reported', dir: 'desc' }],
    pageLength: 25,
    autoWidth: false,
    stateSave: true,
    layout: {
      top: null,
      topStart: null,
      topEnd: null,
      bottomStart: 'pageLength',
      bottomEnd: 'paging',
      bottom2Start: 'info',
    },
  }
  return (
    <>
      <SearchForm
        formRef={formRef}
        table={table}
        defaultOrder={defaultOrder}
        states={loaderData.states}
        naics={loaderData.naics} />
      <Datatable
        id='id_search_table'
        collection='reports'
        ref={table}
        columns={columns}
        searchFormRef={formRef}
        options={options} />
    </>
  )
}
