import type { Route } from './+types/report'
import { fetchok } from '../lib/utils'
import Detail from '../components/ReportDetail'
import Artifacts from '../components/ReportArtifacts'
import Naics from '../components/ReportNaics'
import Related from '../components/RelatedReports'

export async function clientLoader({ params }: Route.LoaderArgs) {
  const rep = await fetchok(`/api/v0/reports/${params.id}`)
  const report = await rep.json()
  return { report }
}

export default function ({ loaderData }) {
  const { report } = loaderData
  return (
    <div className='report-view'>
      <Detail report={report} />
      <Artifacts report={report} />
      <Naics report={report} />
      <Related report={report} />
    </div>
  )
}
