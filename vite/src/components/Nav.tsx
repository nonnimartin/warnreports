import { NavLink } from 'react-router'

export default function () {
  const links = [
    ['/', 'Home'],
    ['/search', 'Search'],
    ['/feed', 'Feed'],
    ['/api', 'API'],
    ['/about', 'About'],
  ]
  return (
    <div className="container-flex bg-light">
      <div className="container" id="id_mainnav">
        <nav className="nav main-nav nav-pills">
          {links.map(([to, text]) => (
            <NavLink key={to} to={to} className='nav-link'>
              {text}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  )
}
