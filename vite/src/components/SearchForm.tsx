import type { DataTableRef } from 'datatables.net-react'

interface SearchFormProps {
  formRef: React.RefObject<HTMLFormElement>
  states: any[]
  naics: any[]
  table: React.RefObject<DataTableRef>
  defaultOrder: any
}

export default function (
  {
    formRef,
    states,
    naics,
    table,
    defaultOrder,
  }: SearchFormProps
) {

  const redrawDelay = 100
  let reqTimeout: any = null
  let hash = ''

  function handleResetClick(e: React.MouseEvent) {
    e.preventDefault()
    clearTimeout(reqTimeout)
    formRef.current.querySelectorAll(
      'input.form-control, select.form-select'
    ).forEach(el => {
      (el as HTMLInputElement).value = ''
    })
    const api = table?.current!.dt()
    if (!api) {
      return
    }
    if (defaultOrder) {
      // @ts-ignore
      api.state({ order: defaultOrder })
    }
    hash = getHash()
    api.draw()
  }

  function getHash() {
    const params = new URLSearchParams
    for (const [key, value] of new FormData(formRef.current).entries()) {
      const { length } = value as string
      if (key === 'text' && length < 2) {
        continue
      }
      if (length) {
        params.append(key, value as string)
      }
    }
    return params.toString()
  }

  function queueDraw() {
    clearTimeout(reqTimeout)
    const newHash = getHash()
    if (hash !== newHash) {
      reqTimeout = setTimeout(() => {
        hash = newHash
        const api = table?.current!.dt()
        if (api) {
          api.draw()
        }
      }, redrawDelay)
    }
  }

  return (
    <form
      className="row g-3 search-form"
      ref={formRef}
      onKeyUp={() => queueDraw()}
      onKeyDown={() => queueDraw()}
      onChange={() => queueDraw()}
      onSubmit={(e) => {
        e.preventDefault()
        queueDraw()
      }}
    >
      <div className="col-3">
        <label htmlFor="search_text">Search</label>
        <input className="form-control" name="text" id="search_text" />
      </div>
      <div className="col-1">
        <label htmlFor="search_state">State</label>
        <select className="form-select" name="state" id="search_state">
          <option value="">-</option>
          {...states.map(({ id }) => (<option value={id}>{id}</option>))}
        </select>
      </div>
      <div className="col-2">
        <label htmlFor="search_reported_min">Reported min.</label>
        <input className="form-control" name="reported_min" type="date" id="search_reported_min" />
      </div>
      <div className="col-2">
        <label htmlFor="search_reported_max">Reported max.</label>
        <input className="form-control" name="reported_max" type="date" id="search_reported_max" />
      </div>
      <div className="col-1">
        <label htmlFor="search_employees_min">Emps. min.</label>
        <input className="form-control" name="employees_min" type="number" id="search_employees_min" />
      </div>
      <div className="col-2">
        <label htmlFor="search_naics">Industry</label>
        <select className="form-select" name="naics" id="search_naics">
          <option value="">-</option>
          {...naics.map(({ id, title }) => (<option value={id}>{id} - {title}</option>))}
        </select>
      </div>
      <div className="col-1">
        <label htmlFor="search_clear"></label>
        <input type="submit" className="hidden" />
        <button
          className="form-control clear-form btn btn-secondary"
          onClick={handleResetClick}
        >Clear</button>
      </div>
    </form>
  )
}