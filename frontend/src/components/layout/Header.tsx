/**
 * Header component — IBKR-style top bar with layout controls.
 */

import { useAppStore } from '../../stores/appStore'
import { useLayoutStore } from '../../stores/layoutStore'
import { clsx } from 'clsx'

export function Header() {
  const { lastUpdate, loading, fetchAll } = useAppStore()
  const { activePreset, setPanelOpen } = useLayoutStore()

  const presetLabel: Record<string, string> = {
    full: 'Full',
    momentum: 'Momentum',
    signals: 'Signals',
    custom: 'Custom',
  }

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
        <span className={clsx(
          'badge text-2xs ml-2',
          activePreset === 'custom' ? 'badge-yellow' : 'badge-blue'
        )}>
          {presetLabel[activePreset] || 'Custom'}
        </span>
      </div>

      {/* Right: Controls */}
      <div className="flex items-center gap-3">
        {lastUpdate && (
          <span className="text-2xs text-text-muted font-mono hidden sm:inline">
            {new Date(lastUpdate).toLocaleTimeString()}
          </span>
        )}
        <button
          onClick={fetchAll}
          disabled={loading}
          className="px-2.5 py-1 text-xs rounded bg-surface-3 hover:bg-accent-blue/20 text-text-secondary hover:text-accent-blue transition-colors disabled:opacity-50"
        >
          {loading ? '⟳' : '↻'}
        </button>
        <button
          onClick={() => setPanelOpen(true)}
          className="px-2.5 py-1 text-xs rounded bg-surface-3 hover:bg-accent-purple/20 text-text-secondary hover:text-accent-purple transition-colors"
          title="Layout Settings"
        >
          ⚙
        </button>
      </div>
    </header>
  )
}
