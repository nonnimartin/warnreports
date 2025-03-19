import React from 'react'

export default function () {
  return (
    <form className="row g-3 search-form">
      <div className="col-3">
        <label htmlFor="search_text">Search</label>
        <input className="form-control" name="text" id="search_text" />
      </div>
      <div className="col-1">
        <label htmlFor="search_state">State</label>
        <select className="form-select" name="state" id="search_state">
          <option value="">-</option>
        </select>
      </div>
      <div className="col-2">
        <label htmlFor="search_reported_min">Reported min.</label>
        <input className="form-control" name="reported_min" type="date" id="search_reported_min" />
      </div>
      <div className="col-2">
        <label htmlFor="search_reported_max">Reported max.</label>
        <input className="form-control" name="reported_max" type="date" id="search_reported_max" />
      </div>
      <div className="col-1">
        <label htmlFor="search_employees_min">Emps. min.</label>
        <input className="form-control" name="employees_min" type="number" id="search_employees_min" />
      </div>
      <div className="col-2">
        <label htmlFor="search_naics">Industry</label>
        <select className="form-select" name="naics" id="search_naics">
          <option value="">-</option>
        </select>
      </div>
      <div className="col-1">
        <label htmlFor="search_clear"></label>
        <input type="submit" className="hidden" />
        <button
          className="form-control clear-form btn btn-secondary"
          id="search_clear">Clear</button>
      </div>
    </form>
  )
}