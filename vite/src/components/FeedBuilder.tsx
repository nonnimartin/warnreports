import { xml } from '@codemirror/lang-xml'
import { vscodeDark } from '@uiw/codemirror-theme-vscode'
import CodeMirror from '@uiw/react-codemirror'
import { useState, useRef } from 'react'
import '../cm.css'
import Datatable from './Datatable'
import { fetchok } from '../lib/utils'

interface FeedBuilderProps {
  states: any[]
  params: URLSearchParams
}
const sample =
  `<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="en">
  <id>https://warnreports.org/feed/atom/c3RhdGU9Q1QmdGV4dD0lMjJmb28rYmFyJTIy</id>
  <title>warnreports CT "foo bar"</title>
  <updated>2025-03-21T11:58:25.302388+00:00</updated>
  <link href="https://warnreports.org/feed/atom/c3RhdGU9Q1QmdGV4dD0lMjJmb28rYmFyJTIy" rel="self"/>
  <subtitle>warnreports CT "foo bar"</subtitle>
</feed>`
const extensions = [xml()]

export default function ({ states, params }: FeedBuilderProps) {
  const [feedInfo, setFeedInfo] = useState()
  return (
    <>
      <h2>Custom Feed</h2>
      <FeedForm states={states} params={params} />
      <FeedTable setFeedInfo={setFeedInfo} />
      {/* {feedInfo} */}
    </>
  )
}

function FeedForm({ states, params }: FeedBuilderProps) {
  const formRef = useRef(null)

  function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    const formData = new FormData(formRef.current as HTMLFormElement)
    const params = new URLSearchParams
    for (const [key, value] of formData.entries()) {
      if (value) {
        params.set(key, value as string)
      }
    }
    const search = params.size ? `?${params}` : ''
    if (search !== window.location.search) {
      const href = `${window.location.pathname}${search}`
      window.location.href = href
    }
  }

  function onResetClick(e: React.MouseEvent) {
    e.preventDefault()
    if (window.location.search) {
      window.location.href = window.location.pathname
    } else {
      (formRef.current as HTMLFormElement).reset()
    }
  }

  return (
    <form
      className="row g-3"
      ref={formRef}
      id="id_feed_form"
      onSubmit={onSubmit}>
      <div className="col-4">
        <label htmlFor="search_text">Search</label>
        <input
          className="form-control"
          name="text"
          id="search_text"
          defaultValue={params.get('text') || ''} />
      </div>
      <div className="col-2">
        <label htmlFor="search_state">State</label>
        <select
          className="form-select"
          name="state"
          id="search_state"
          defaultValue={params.get('state') || ''}>
          <option value="">-</option>
          {...states.map(({ id }) => (<option value={id}>{id}</option>))}
        </select>
      </div>
      <div className="col-2">
        <label htmlFor="search_employees_min">Employees</label>
        <input
          className="form-control"
          name="employees_min"
          type="number"
          id="search_employees_min"
          defaultValue={params.get('employees_min') || ''} />
      </div>
      <div className="col-2">
        <label htmlFor="search_naics">NAICS</label>
        <input
          className="form-control"
          name="naics"
          type="number"
          id="search_naics"
          defaultValue={params.get('naics') || ''} />
      </div>
      <div className="col-1">
        <label htmlFor="search_submit"></label>
        <button
          type="submit"
          className="form-control btn btn-primary"
          id="search_submit">Submit</button>
      </div>
      <div className="col-1">
        <label htmlFor="search_clear"></label>
        <button
          className="form-control form-reset btn btn-secondary"
          id="search_clear"
          onClick={onResetClick}>Clear</button>
      </div>
    </form>
  )
}

function FeedTable({ setFeedInfo }: { setFeedInfo: Function }) {
  let isResponse = false

  function onAjax(res: any, rep: Response) {
    if (isResponse) {
      return
    }
    isResponse = true
    const feedId = rep.headers.get('feed-id') || ''
    setFeedInfo(
      <FeedInfo feedId={feedId} />
    )
  }

  const columns = [
    'state',
    'company',
    'reported',
    'starting',
    'employees',
    'action',
  ]
  const options = {
    pageLength: 10,
    autoWidth: false,
    ordering: false,
    lengthChange: false,
    filter: false,
    layout: {
      bottomStart: null,
    },
  }
  const fixedParams = {
    order: '-reported',
  }
  return (
    <Datatable
      id='feed_table'
      collection='reports'
      columns={columns}
      searchFormId='id_feed_form'
      options={options}
      fixedParams={fixedParams}
      onAjax={onAjax}
    />
  )
}

function FeedInfo({ feedId }: { feedId: string }) {
  return (
    <>
      <FeedMarkup title='Atom' format='atom' feedId={feedId} />
      <FeedMarkup title='RSS' format='rss' feedId={feedId} />
    </>
  )
}

function FeedMarkup(
  {
    title,
    format,
    feedId,
  }: { title: string, format: string, feedId: string }
) {
  const [markup, setMarkup] = useState('')
  let url = `/feed/${format}`
  if (feedId) {
    url = `${url}/${feedId}`
  }
  fetchok(url).then(res => {
    res.text().then(value => setMarkup(value))
  })
  return (
    <CodeMirror
      value={markup}
      readOnly={true}
      extensions={extensions}
      theme={vscodeDark} />
  )
}