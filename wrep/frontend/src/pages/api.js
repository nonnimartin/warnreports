import { StaticComponent } from '../lib/main.js'

export default new StaticComponent($(
    `
    <h2>API Docs</h2>
    <ul>
        <li><a href="/api/docs">Rapidoc</a></li>
        <li><a href="/api/docs/redoc" target="_blank">Redoc</a></li>
        <li><a href="/api/docs/swagger" target="_blank">Swagger</a></li>
        <li><a href="/api/v0/openapi.json">openapi.json</a></li>
    </ul>
    `
))
