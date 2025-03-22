import { useRef, useEffect } from 'react';
import type { Route } from './+types/report'
import { fetchok } from '../lib/utils'
import * as maptilersdk from '@maptiler/sdk';
import "@maptiler/sdk/dist/maptiler-sdk.css";

export async function clientLoader() {
  const rep = await fetchok(`/api/v0/reports?offset=0&limit=25&order=-reported`);
  const report = await rep.json();
  return { report }
}

export default function Map({loaderData}) {
  const { report } = loaderData
  console.log(report);
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

    report.forEach((thisReport) => {

      // make a request to https://api.maptiler.com/geocoding/<CITY>.json?key=<API_KEY>
      // for coordinates


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