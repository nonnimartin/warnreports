import FeedBuilder from '../components/FeedBuilder'
import { fetchok } from '../lib/utils'

export async function clientLoader() {
  const rep = await fetchok(`/api/v0/states`)
  const states: any[] = await rep.json()
  return { states }
}

export default function ({ loaderData }) {
  const params = new URLSearchParams(window.location.search)
  return (
    <div>
      <h1>(WIP)</h1>
      <h2>Full Feed</h2>
      <dl>
        <dt>RSS</dt>
        <dd><a href='/feed/rss' target='_blank'>/feed/rss</a></dd>
        <dt>Atom</dt>
        <dd><a href='/feed/atom' target='_blank'>/feed/atom</a></dd>
      </dl>
      <FeedBuilder
        states={loaderData.states}
        params={params} />
    </div>
  )
}