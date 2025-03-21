import 'rapidoc'

// https://rapidocweb.com/api.html

export default function () {
  const font = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", "Noto Sans", "Liberation Sans", Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol", "Noto Color Emoji"'
  return (
    // @ts-ignore
    <rapi-doc
      spec-url='/api/v0/openapi.json'
      theme='dark'
      show-header='false'
      allow-authentication='false'
      allow-server-selection='false'
      allow-api-list-style-selection='false'
      regular-font={font}
      render-style='view'
    />
  )
}