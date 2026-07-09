import { Component, ErrorInfo, ReactNode } from 'react'

// Global React error boundary (task 3): catches render-time exceptions anywhere
// below it so one broken page shows a fallback instead of a blank white screen.

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error('Unhandled UI error:', error, info.componentStack)
  }

  handleReset = () => this.setState({ hasError: false, error: null })

  render() {
    if (!this.state.hasError) return this.props.children
    if (this.props.fallback) return this.props.fallback
    return (
      <div role="alert" style={{ padding: '2rem', textAlign: 'center' }}>
        <h2>Something went wrong</h2>
        <p>{this.state.error?.message ?? 'An unexpected error occurred.'}</p>
        <button onClick={this.handleReset}>Try again</button>
      </div>
    )
  }
}

export default ErrorBoundary
