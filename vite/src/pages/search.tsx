import coldefs from '../lib/coldefs'
import Datatable from '../components/Datatable'
import SearchForm from '../components/SearchForm'

export default function () {
  const defaultOrder = [{ name: 'reported', dir: 'desc' }]
  const searchForm = (<SearchForm />)
  const opts = {
    order: defaultOrder,
    pageLength: 25,
    autoWidth: false,
    layout: {
      topEnd: null,
      bottomStart: 'pageLength',
      bottomEnd: 'paging',
      bottom2Start: 'info',
      topStart: null,
    },
  }
  const slots = {
    company: (data, type, row) => {
      if (type === 'display') {
        return ( <a href={`/r/${row.id}`}>{data}</a> )
      }
      return data
    }
  }
  return (
    <Datatable
      collection='reports'
      columns={coldefs.reports} 
      searchForm={searchForm}
      options={opts}
      slots={slots} />
  )
}
