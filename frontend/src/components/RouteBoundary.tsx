import { Component, type ReactNode } from 'react'
import { RefreshCw } from 'lucide-react'
import { newerBuildAvailable } from '../hooks/useBuildCheck'

/**
 * Keeps one broken page from blanking the whole site.
 *
 * Before this there was no boundary at all: any render error unmounted the tree and
 * left an empty dark screen with no nav. The common trigger is not a bug in the page —
 * it is a tab still running the previous bundle against a freshly deployed API whose
 * response shape moved. So the first thing the fallback does is ask whether a newer
 * build is live and, if so, reload into it once (sessionStorage guards the loop).
 *
 * Keyed by pathname in Layout, so navigating away resets it.
 */

type Props = { children: ReactNode }
type State = { error: Error | null }

const RELOAD_FLAG = 'sa_boundary_reload'

export class RouteBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error) {
    console.error('[RouteBoundary]', error)
    newerBuildAvailable().then((newer) => {
      let reloaded = false
      try { reloaded = sessionStorage.getItem(RELOAD_FLAG) === '1' } catch { /* storage blocked */ }
      if (newer && !reloaded) {
        try { sessionStorage.setItem(RELOAD_FLAG, '1') } catch { /* storage blocked */ }
        window.location.reload()
      }
    })
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="card route-error" role="alert">
        <h3 className="card-title">This section failed to load</h3>
        <p className="route-error__msg">
          The rest of the site still works — pick another tab above, or reload to fetch the latest version.
        </p>
        <button className="btn btn-primary route-error__btn" onClick={() => window.location.reload()}>
          <RefreshCw size={13} /> Reload
        </button>
        <code className="route-error__detail">{this.state.error.message}</code>
      </div>
    )
  }
}
