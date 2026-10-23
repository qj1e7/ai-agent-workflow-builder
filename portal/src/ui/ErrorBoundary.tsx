import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Button } from './Button'
import styles from './ErrorBoundary.module.css'

export function ErrorScreen() {
  return (
    <div className={styles['screen']} role="alert">
      <h1>Something went wrong</h1>
      <p>The page stopped working. Reload it to try again. If it keeps happening, tell the team what you were doing.</p>
      <Button variant="primary" onClick={() => window.location.reload()}>
        Reload the page
      </Button>
    </div>
  )
}

interface Props {
  resetKey?: string
  children: ReactNode
}

export class ErrorBoundary extends Component<Props, { failed: boolean }> {
  override state = { failed: false }

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true }
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(error, info.componentStack)
  }

  override componentDidUpdate(previous: Props): void {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) this.setState({ failed: false })
  }

  override render(): ReactNode {
    return this.state.failed ? <ErrorScreen /> : this.props.children
  }
}
