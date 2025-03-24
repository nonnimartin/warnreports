import {USAMap} from '@mirawision/usa-map-react';
import {fetchok} from '../lib/utils'
import {useRef, useEffect} from 'react';

export async function clientLoader() {
  const rep = await fetchok(`/api/v0/reports?offset=0&limit=25&order=-reported`);
  const report = await rep.json();
  return { report }
}

export default function USMap({loaderData}) {
  const { report } = loaderData;
  const map = useRef(null);

  useEffect(() => {
    if (map.current) return;
  })
  
  let defaultState = {};

  report.forEach((thisReport) => {
    let state = thisReport['state'];
    if (!defaultState.hasOwnProperty(state)){
      defaultState[state] = {'fill':  '#'+(Math.random() * 0xFFFFFF << 0).toString(16).padStart(6, '0')}
    }
  });
  return (
    <div style={{display: 'flex',  justifyContent:'center', alignItems:'center'}}>
      <h1>Recent Warn Reports</h1>
      <USAMap customStates={defaultState} />
    </div>
  );
};