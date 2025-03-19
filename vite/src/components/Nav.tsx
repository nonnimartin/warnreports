import React from 'react'
import { NavLink } from 'react-router'

export default function Component() {
  return (
    <div className="container-flex bg-light">
      <div className="container" id="id_mainnav">
        <nav>
          <NavLink to='/' className='nav-link'>Home</NavLink>
          <NavLink to='/search' className='nav-link'>Search</NavLink>
          <NavLink to='/about' className='nav-link'>About</NavLink>
        </nav>
      </div>
    </div>
  )
}
