/**
 * Market Pulse Widget — Hero section showing market regime + sentiment.
 */

import { useAppStore } from '../../stores/appStore'
import { clsx } from 'clsx'

const regimeColors: Record<string, string> = {
  bullish: 'text-accent-green',
  neutral: 'text-accent-yellow',
  cautious: 'text-accent-orange',
  bearish: 'text-accent-red',
  STRONG_TREND: 'text-accent-green',
  STRONG: 'text-accent-green',
  NEUTRAL: 'text-accent-yellow',
  WEAK: 'text-accent-red',
}

const moodEmoji: Record<string, string> = {
  'RISK-ON': '🟢',
  'RISK-ON Leaning': '🟡',
  'NEUTRAL': '⚪',
  'RISK-OFF': '🔴',
}

function ScoreGauge({ score, label }: { score: number | null; label: string }) {
  const pct = score != null ? Math.max(0, Math.min(100, score)) : 0
  const color = pct >= 70 ? 'bg-accent-green' : pct >= 60 ? 'bg-accent-yellow' : pct >= 40 ? 'bg-accent-orange' : 'bg-accent-red'

  return (
    <div className="flex flex-col items-center gap-1">
      <span className="text-2xs text-text-muted uppercase">{label}</span>
      <span className="text-lg font-mono font-bold text-text-primary">
        {score != null ? score.toFixed(1) : '—'}
      </span>
      <div className="w-16 score-bar">
        <div className={clsx('score-bar-fill', color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export function MarketPulseWidget() {
  const { marketOverview } = useAppStore()

  if (!marketOverview) {
    return (
      <div className="widget-card">
        <div className="widget-header"><span className="widget-title">Market Pulse</span></div>
        <div className="widget-body text-center text-text-muted text-sm py-6">Loading...</div>
      </div>
    )
  }

  const { pulse, sentiment } = marketOverview
  const mood = sentiment.mood
  const spy = sentiment.spy
  const qqq = sentiment.qqq

  return (
    <div className="widget-card">
      <div className="widget-header">
        <span className="widget-title">Market Pulse</span>
        <span className="text-2xs text-text-muted font-mono">{marketOverview.date}</span>
      </div>
      <div className="widget-body">
        <div className="flex items-center justify-between flex-wrap gap-4">
          {/* Mood */}
          <div className="flex items-center gap-3">
            <span className="text-2xl">{moodEmoji[mood] || '⚪'}</span>
            <div>
              <div className="text-sm font-semibold text-text-primary">{mood}</div>
              {sentiment.tech_vs_broad != null && (
                <div className="text-2xs text-text-muted">
                  QQQ vs SPY: <span className={sentiment.tech_vs_broad > 0 ? 'text-accent-green' : 'text-accent-red'}>
                    {sentiment.tech_vs_broad > 0 ? '+' : ''}{sentiment.tech_vs_broad.toFixed(1)}pt
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Market Pulse Score */}
          {pulse && (
            <div className="flex items-center gap-2">
              <span className={clsx('text-xs font-medium', regimeColors[pulse.regime] || 'text-text-secondary')}>
                {pulse.regime.toUpperCase()}
              </span>
              <ScoreGauge score={pulse.composite_score} label="Pulse" />
            </div>
          )}

          {/* SPY / QQQ Scores */}
          <div className="flex gap-4">
            {spy && <ScoreGauge score={spy.score} label="SPY" />}
            {qqq && <ScoreGauge score={qqq.score} label="QQQ" />}
          </div>

          {/* Price Info */}
          <div className="flex gap-4 text-xs font-mono">
            {spy && spy.price && (
              <div>
                <span className="text-text-muted">SPY </span>
                <span className="text-text-primary">${spy.price.toFixed(2)}</span>
                <span className={clsx('ml-1', (spy.daily_change_pct ?? 0) >= 0 ? 'text-accent-green' : 'text-accent-red')}>
                  {(spy.daily_change_pct ?? 0) >= 0 ? '+' : ''}{(spy.daily_change_pct ?? 0).toFixed(2)}%
                </span>
              </div>
            )}
            {qqq && qqq.price && (
              <div>
                <span className="text-text-muted">QQQ </span>
                <span className="text-text-primary">${qqq.price.toFixed(2)}</span>
                <span className={clsx('ml-1', (qqq.daily_change_pct ?? 0) >= 0 ? 'text-accent-green' : 'text-accent-red')}>
                  {(qqq.daily_change_pct ?? 0) >= 0 ? '+' : ''}{(qqq.daily_change_pct ?? 0).toFixed(2)}%
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
