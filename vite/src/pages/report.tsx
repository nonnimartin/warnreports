import { useLoaderData } from 'react-router'
import Related from '../components/RelatedReports'
import Artifacts from '../components/ReportArtifacts'
import Detail from '../components/ReportDetail'
import Naics from '../components/ReportNaics'
import type { ReportData } from '../lib/models'
import { fetchok } from '../lib/utils'
import type { Route } from './+types/report'

type LoaderData = { report: ReportData }

export async function clientLoader({ params }: Route.LoaderArgs): Promise<LoaderData> {
  const rep = await fetchok(`/api/v0/reports/${params.id}`)
  const report = await rep.json() as ReportData
  return { report }
}

export default function () {
  const { report } = useLoaderData() as LoaderData
  return (
    <div className='report-view'>
      <Detail report={report} />
      <Artifacts report={report} />
      <Naics report={report} />
      <Related report={report} />
    </div>
  )
}
