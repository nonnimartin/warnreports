import { type RouteConfig, route, index } from '@react-router/dev/routes'

const page = (name: string) => `./pages/${name}.tsx`
const pageroute = (name: string) => route(name, page(name))

export default [
  index(page('home')),
  ...[
    'search',
    'feed',
    'api',
    'about',
  ].map(pageroute),
  route('r/:id', page('report')),
  route('*', './catchall.tsx'),
] satisfies RouteConfig
