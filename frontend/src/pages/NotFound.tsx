import { Link } from 'react-router-dom'

export function NotFound() {
  return (
    <div className="state-box">
      <div>
        <strong>Page not found.</strong>
        <p>
          <Link to="/">Back to the overview</Link>
        </p>
      </div>
    </div>
  )
}
