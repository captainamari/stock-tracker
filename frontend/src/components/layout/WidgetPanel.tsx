/**
 * Widget Panel — Toggle visibility of widgets + switch layout presets.
 */

import { useLayoutStore, type LayoutPreset } from '../../stores/layoutStore'
import { clsx } from 'clsx'

const PRESETS: { key: LayoutPreset; label: string; icon: string }[] = [
  { key: 'full', label: 'Full Dashboard', icon: '▣' },
  { key: 'momentum', label: 'Momentum Focus', icon: '📊' },
  { key: 'signals', label: 'Signals Only', icon: '⚡' },
]

export function WidgetPanel() {
  const { widgets, activePreset, panelOpen, setPreset, toggleWidget, setPanelOpen, resetLayout } = useLayoutStore()

  if (!panelOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={() => setPanelOpen(false)} />

      {/* Panel */}
      <div className="relative ml-auto w-72 h-full bg-surface-1 border-l border-border shadow-2xl flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary">Layout Settings</h2>
          <button
            onClick={() => setPanelOpen(false)}
            className="text-text-muted hover:text-text-primary text-lg"
          >
            ×
          </button>
        </div>

        {/* Presets */}
        <div className="px-4 py-3 border-b border-border">
          <div className="text-2xs text-text-muted uppercase mb-2 font-medium">Presets</div>
          <div className="space-y-1">
            {PRESETS.map(p => (
              <button
                key={p.key}
                onClick={() => setPreset(p.key)}
                className={clsx(
                  'w-full text-left px-3 py-2 rounded text-xs transition-colors',
                  activePreset === p.key
                    ? 'bg-accent-blue/20 text-accent-blue border border-accent-blue/30'
                    : 'bg-surface-2 text-text-secondary hover:bg-surface-3'
                )}
              >
                <span className="mr-2">{p.icon}</span>
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Widget Toggles */}
        <div className="px-4 py-3 flex-1 overflow-y-auto">
          <div className="text-2xs text-text-muted uppercase mb-2 font-medium">Widgets</div>
          <div className="space-y-1.5">
            {widgets.map(w => (
              <label
                key={w.id}
                className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-surface-2 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={w.visible}
                  onChange={() => toggleWidget(w.id)}
                  className="rounded border-border bg-surface-3 text-accent-blue focus:ring-accent-blue/50 w-3.5 h-3.5"
                />
                <span className="text-xs text-text-primary">{w.title}</span>
              </label>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-border">
          <button
            onClick={resetLayout}
            className="w-full px-3 py-1.5 rounded text-xs bg-surface-3 text-text-secondary hover:text-text-primary hover:bg-surface-2 transition-colors"
          >
            Reset to Default
          </button>
        </div>
      </div>
    </div>
  )
}
