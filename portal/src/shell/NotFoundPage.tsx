import { Link } from 'react-router'
import { PageHead } from './PageHead'

export function NotFoundPage() {
  return (
    <>
      <PageHead heading="Page not found" lead="There is nothing at this address." />
      <p>
        <Link to="/">Go to Home</Link>
      </p>
    </>
  )
}
