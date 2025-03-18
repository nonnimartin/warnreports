import { type RouteConfig, route } from '@react-router/dev/routes'

export default [
  route('/', './pages/home.tsx'),
  route('/search', './pages/search.tsx'),
  route('/about', './pages/about.tsx'),
  // * matches all URLs, the ? makes it optional so it will match / as well
  route('*?', 'catchall.tsx'),
] satisfies RouteConfig
