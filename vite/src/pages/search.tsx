import Datatable from '../components/Datatable'
import SearchForm from '../components/SearchForm'
import { fetchok } from '../lib/utils'

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
  const columns = [
    'state',
    'company',
    'reported',
    'starting',
    'employees',
    'action',
  ]
  const defaultOrder = [{ name: 'reported', dir: 'desc' }]
  const searchForm = (
    <SearchForm
      id='id_search_form'
      states={loaderData.states}
      naics={loaderData.naics} />
  )
  const options = {
    order: defaultOrder,
    pageLength: 25,
    autoWidth: false,
    layout: {
      topStart: null,
      topEnd: null,
      bottomStart: 'pageLength',
      bottomEnd: 'paging',
      bottom2Start: 'info',
      top: () => document.getElementById('id_search_form'),
    },
  }
  return (
    <Datatable
      collection='reports'
      columns={columns}
      searchForm={searchForm}
      options={options} />
  )
}
