import * as React from 'react';
import Map from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import * as maptilersdk from '@maptiler/sdk';

const map = (<Map
initialViewState={{
  longitude: -90.2446,
  latitude: 38.12924,
  zoom: 3
}}
style={{width: 600, height: 400}}
mapStyle="https://api.maptiler.com/maps/0195b4e1-ab90-7ad0-9fb2-445919d31f36/style.json?key=ADifuwf2XQ4HVeGoLsWP"
/>);

const marker = new maptilersdk.Marker()
  .setLngLat([30.5, 50.5])
  .addTo(map);

function App() {
  return (map);
}

export default App