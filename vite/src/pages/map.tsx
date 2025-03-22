import React, { useRef, useEffect } from 'react';
import * as maptilersdk from '@maptiler/sdk';
import "@maptiler/sdk/dist/maptiler-sdk.css";

export default function Map() {
  const mapContainer = useRef(null);
  const map = useRef(null);
  const usa = { lng: -95.2446, lat: 38.12924 };
  const zoom = 3;
  maptilersdk.config.apiKey = 'ADifuwf2XQ4HVeGoLsWP';

  useEffect(() => {
    if (map.current) return; // stops map from intializing more than once

    map.current = new maptilersdk.Map({
      container: mapContainer.current,
      center: [usa.lng, usa.lat],
      zoom: zoom
    });

  }, [usa.lng, usa.lat, zoom]);

  return (
    <div className="map-wrap">
      <div ref={mapContainer} className="map" />
    </div>
  );
}