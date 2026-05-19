/**
 * Momentum Heatmap Widget — Three-layer heatmap (Market → Sector → Stock).
 */

import { useAppStore } from '../../stores/appStore'
import { clsx } from 'clsx'
import type { HeatmapItem } from '../../types'

function scoreColor(score: number | null): string {
  if (score == null) return 'bg-surface-3'
  if (score >= 70) return 'bg-accent-green/30 border-accent-green/50'
  if (score >= 60) return 'bg-accent-green/15 border-accent-green/30'
  if (score >= 50) return 'bg-accent-yellow/15 border-accent-yellow/30'
  if (score >= 40) return 'bg-accent-orange/15 border-accent-orange/30'
  return 'bg-accent-red/20 border-accent-red/40'
}

function scoreTextColor(score: number | null): string {
  if (score == null) return 'text-text-muted'
  if (score >= 70) return 'text-accent-green'
  if (score >= 60) return 'text-accent-green'
  if (score >= 50) return 'text-accent-yellow'
  if (score >= 40) return 'text-accent-orange'
  return 'text-accent-red'
}

function HeatmapCell({ item, onClick }: { item: HeatmapItem; onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        'rounded border px-2 py-1.5 text-left transition-all hover:scale-[1.02] hover:brightness-110',
        scoreColor(item.score),
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-text-primary truncate">{item.symbol}</span>
        <span className={clsx('text-xs font-mono font-bold', scoreTextColor(item.score))}>
          {item.score != null ? item.score.toFixed(0) : '—'}
        </span>
      </div>
      {item.delta_1d != null && (
        <div className={clsx('text-2xs font-mono mt-0.5', item.delta_1d >= 0 ? 'text-accent-green' : 'text-accent-red')}>
          {item.delta_1d >= 0 ? '▲' : '▼'} {Math.abs(item.delta_1d).toFixed(1)}
        </div>
      )}
    </button>
  )
}

export function MomentumHeatmap() {
  const { heatmap, setSelectedSymbol } = useAppStore()

  if (!heatmap) {
    return (
      <div className="widget-card">
        <div className="widget-header"><span className="widget-title">Momentum Heatmap</span></div>
        <div className="widget-body text-center text-text-muted text-sm py-8">Loading...</div>
      </div>
    )
  }

  return (
    <div className="widget-card">
      <div className="widget-header">
        <span className="widget-title">Momentum Heatmap</span>
        <span className="text-2xs text-text-muted font-mono">{heatmap.date}</span>
      </div>
      <div className="widget-body space-y-3">
        {/* Layer 0: Market */}
        {heatmap.market.length > 0 && (
          <div>
            <div className="text-2xs text-text-muted uppercase mb-1.5 flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-accent-blue" /> Market Sentiment
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              {heatmap.market.map(item => (
                <HeatmapCell key={item.symbol} item={item} onClick={() => setSelectedSymbol(item.symbol)} />
              ))}
            </div>
          </div>
        )}

        {/* Layer 1: Sectors */}
        {heatmap.sectors.length > 0 && (
          <div>
            <div className="text-2xs text-text-muted uppercase mb-1.5 flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-accent-purple" /> Sector ETFs
            </div>
            <div className="grid grid-cols-3 gap-1.5">
              {heatmap.sectors.map(item => (
                <HeatmapCell key={item.symbol} item={item} onClick={() => setSelectedSymbol(item.symbol)} />
              ))}
            </div>
          </div>
        )}

        {/* Layer 2: Stocks */}
        {heatmap.stocks.length > 0 && (
          <div>
            <div className="text-2xs text-text-muted uppercase mb-1.5 flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-accent-yellow" /> Individual Stocks
            </div>
            <div className="grid grid-cols-3 sm:grid-cols-4 gap-1.5">
              {heatmap.stocks.map(item => (
                <HeatmapCell key={item.symbol} item={item} onClick={() => setSelectedSymbol(item.symbol)} />
              ))}
            </div>
          </div>
        )}

        {heatmap.market.length === 0 && heatmap.sectors.length === 0 && heatmap.stocks.length === 0 && (
          <div className="text-center text-text-muted text-sm py-4">
            No momentum data. Run pipeline to populate.
          </div>
        )}
      </div>
    </div>
  )
}
