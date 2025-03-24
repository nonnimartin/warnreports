import { useState } from 'react';
import ReactMapGL, { Source, Layer } from 'react-map-gl/maplibre'; // Use react-map-gl/maplibre
import 'maplibre-gl/dist/maplibre-gl.css'; // Import MapLibre GL CSS
import * as maptilersdk from '@maptiler/sdk';

// Set your MapTiler API key
maptilersdk.config.apiKey = 'ADifuwf2XQ4HVeGoLsWP'; // Replace with your actual key

const Map = () => {
  const [viewport, setViewport] = useState({
    latitude: 37.8, // Center of the U.S.
    longitude: -96,
    zoom: 3, // Zoom level to show the entire U.S.
  });

  // GeoJSON data for smaller squares centered within states
  const statesGeoJSON = {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { name: 'California' },
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [-119.5, 36.5], // Top-left corner of the square
              [-116.5, 36.5], // Top-right corner
              [-116.5, 38.5], // Bottom-right corner
              [-119.5, 38.5], // Bottom-left corner
              [-119.5, 36.5], // Close the polygon
            ],
          ],
        },
      },
      {
        type: 'Feature',
        properties: { name: 'Texas' },
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [-100.0, 31.0], // Top-left corner of the square
              [-97.0, 31.0], // Top-right corner
              [-97.0, 33.0], // Bottom-right corner
              [-100.0, 33.0], // Bottom-left corner
              [-100.0, 31.0], // Close the polygon
            ],
          ],
        },
      },
      // Add more states as needed
    ],
  };

  // Define the MapTiler style URL
  const mapStyle = `https://api.maptiler.com/maps/streets/style.json?key=${maptilersdk.config.apiKey}`;

  return (
    <div style={{ width: '100%', height: '100vh' }}>
      <ReactMapGL
        {...viewport}
        width="100%"
        height="100%"
        mapStyle={mapStyle}
        onViewportChange={setViewport}
        scrollZoom={false}
        dragPan={false}
        doubleClickZoom={false} 
      >
        {/* Add a GeoJSON layer for the smaller squares */}
        <Source id="states-data" type="geojson" data={statesGeoJSON}>
          <Layer
            id="states-fill"
            type="fill"
            paint={{
              'fill-color': [
                'match',
                ['get', 'name'],
                'California', '#FF0000', 
                'Texas', '#00FF00', 
                '#888888', 
              ],
              'fill-opacity': 0.6, 
            }}
          />
          <Layer
            id="states-outline"
            type="line"
            paint={{
              'line-color': '#000000', 
              'line-width': 2,
            }}
          />
        </Source>
      </ReactMapGL>
    </div>
  );
};

export default Map;