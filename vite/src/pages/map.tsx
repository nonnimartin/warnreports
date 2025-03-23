import { useRef, useEffect } from 'react';
import type { Route } from './+types/report'
import { fetchok } from '../lib/utils'
import * as maptilersdk from '@maptiler/sdk';
import "@maptiler/sdk/dist/maptiler-sdk.css";

export async function clientLoader() {
  const rep = await fetchok(`/api/v0/reports?offset=0&limit=25&order=-reported`);
  const reports = await rep.json();
  let queryString = '';
  let addedLocations = [];
  for (const report in reports){
    let reportObj = reports[report];
    console.log(reportObj);
    if (reportObj.location == null){ continue }
    console.log(reportObj.location);
    if (!addedLocations.includes(reportObj.location)) queryString += reportObj.location + ';';
    console.log(addedLocations);
    addedLocations.push(reportObj.location);
  }
  console.log(queryString);
  let coordsMap = await fetchok(`https://api.maptiler.com/geocoding/` + queryString + `.json?key=ADifuwf2XQ4HVeGoLsWP&country=us`);
  let locationMap = {};
  console.log('json');
  console.log(coordsMap);
  coordsMap.json().then((response) => {
    for (const location in response){
      let thisLocation = response[location];
      console.log(thisLocation);
      if (thisLocation['features'].length == 0) continue;
      if (thisLocation['features'][0].length == 0) continue;
      let longitude = thisLocation['features'][0]['geometry']['coordinates'][0];
      console.log(longitude);
      let latitude = thisLocation['features'][0]['geometry']['coordinates'][1];
      console.log(latitude);
      let placeName = thisLocation['features'][0]['place_name'];
      locationMap[placeName] = {'latitude':latitude, 'longitude':longitude};
    }
    console.log(locationMap);
    reports['coordsMap'] = locationMap;
  });
  return reports;
}

export default function Map({loaderData}) {
  const { reports } = loaderData ?? {}
  const mapContainer = useRef(null);
  const map = useRef(null);
  const usa = { lng: -95.2446, lat: 38.12924 };
  const zoom = 3;
  maptilersdk.config.apiKey = 'ADifuwf2XQ4HVeGoLsWP';

  useEffect(() => {
    if (map.current) return;

    map.current = new maptilersdk.Map({
      container: mapContainer.current,
      center: [usa.lng, usa.lat],
      zoom: zoom
    });
    console.log(reports);
    for (const report of reports)((thisReport) => {
    console.log('this report');
    console.log(thisReport);

    //Adding a marker
      let marker = new maptilersdk.Marker()
        .setLngLat([30.5, 50.5])
        .addTo(map.current);
  });

  }, [usa.lng, usa.lat, zoom]);

  return (
    <div className="map-wrap">
      <div ref={mapContainer} className="map" />
    </div>
  );
}