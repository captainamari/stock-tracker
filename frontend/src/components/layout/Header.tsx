/**
 * Header component — IBKR-style top bar.
 */

import { useAppStore } from '../../stores/appStore'

export function Header() {
  const { lastUpdate, loading, fetchAll } = useAppStore()

  return (
    <header className="h-12 bg-surface-1 border-b border-border flex items-center justify-between px-4 shrink-0">
      {/* Left: Logo + Title */}
      <div className="flex items-center gap-3">
        <div className="w-7 h-7 rounded bg-accent-blue flex items-center justify-center">
          <span className="text-xs font-bold text-white">ST</span>
        </div>
        <h1 className="text-sm font-semibold text-text-primary tracking-wide">
          Trading Intelligence Platform
        </h1>
      </div>

      {/* Right: Status + Refresh */}
      <div className="flex items-center gap-4">
        {lastUpdate && (
          <span className="text-2xs text-text-muted font-mono">
            Updated: {new Date(lastUpdate).toLocaleTimeString()}
          </span>
        )}
        <button
          onClick={fetchAll}
          disabled={loading}
          className="px-3 py-1 text-xs rounded bg-surface-3 hover:bg-accent-blue/20 text-text-secondary hover:text-accent-blue transition-colors disabled:opacity-50"
        >
          {loading ? '⟳ Loading...' : '↻ Refresh'}
        </button>
      </div>
    </header>
  )
}
