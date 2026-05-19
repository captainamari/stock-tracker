/**
 * Position Summary Widget — Holdings overview with actions.
 */

import { useAppStore } from '../../stores/appStore'
import { clsx } from 'clsx'

export function PositionSummary() {
  const { momentumScores } = useAppStore()

  // Only show stock-level scores
  const stockScores = momentumScores.filter(s => s.layer === 'stock')

  // Sort by urgency then score
  const urgencyOrder: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3, NONE: 4 }
  const sorted = [...stockScores].sort((a, b) => {
    const ua = urgencyOrder[a.urgency] ?? 9
    const ub = urgencyOrder[b.urgency] ?? 9
    if (ua !== ub) return ua - ub
    return (b.final_score ?? 0) - (a.final_score ?? 0)
  })

  function getAction(score: number | null, urgency: string): { text: string; color: string } {
    if (urgency === 'CRITICAL') return { text: 'EXIT', color: 'text-accent-red' }
    if (score == null) return { text: '—', color: 'text-text-muted' }
    if (score >= 70) return { text: 'HOLD 100%', color: 'text-accent-green' }
    if (score >= 60) return { text: 'HOLD', color: 'text-accent-green' }
    if (score >= 50) return { text: 'WATCH', color: 'text-accent-yellow' }
    if (score >= 40) return { text: 'REDUCE', color: 'text-accent-orange' }
    return { text: 'SELL', color: 'text-accent-red' }
  }

  return (
    <div className="widget-card">
      <div className="widget-header">
        <span className="widget-title">Position Summary</span>
        <span className="text-2xs text-text-muted">{sorted.length} stocks</span>
      </div>
      <div className="widget-body">
        {sorted.length === 0 ? (
          <div className="text-center text-text-muted text-sm py-4">No data</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-text-muted text-2xs uppercase border-b border-border">
                  <th className="text-left py-1.5 font-medium">Symbol</th>
                  <th className="text-right py-1.5 font-medium">Score</th>
                  <th className="text-right py-1.5 font-medium">Δ1d</th>
                  <th className="text-right py-1.5 font-medium">Regime</th>
                  <th className="text-right py-1.5 font-medium">Position</th>
                  <th className="text-right py-1.5 font-medium">Action</th>
                  <th className="text-right py-1.5 font-medium">Price</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map(s => {
                  const action = getAction(s.final_score, s.urgency)
                  return (
                    <tr key={s.symbol} className="border-b border-border/50 hover:bg-surface-2/50">
                      <td className="py-1.5 font-semibold text-text-primary">{s.symbol}</td>
                      <td className={clsx('text-right font-mono', 
                        s.final_score != null && s.final_score >= 60 ? 'text-accent-green' : 
                        s.final_score != null && s.final_score >= 40 ? 'text-accent-yellow' : 'text-accent-red'
                      )}>
                        {s.final_score?.toFixed(1) ?? '—'}
                      </td>
                      <td className={clsx('text-right font-mono', 
                        (s.delta_1d ?? 0) >= 0 ? 'text-accent-green' : 'text-accent-red'
                      )}>
                        {s.delta_1d != null ? `${s.delta_1d >= 0 ? '+' : ''}${s.delta_1d.toFixed(1)}` : '—'}
                      </td>
                      <td className="text-right text-text-secondary">{s.regime ?? '—'}</td>
                      <td className="text-right font-mono">
                        {s.position_advice != null ? `${s.position_advice}%` : '—'}
                      </td>
                      <td className={clsx('text-right font-medium', action.color)}>{action.text}</td>
                      <td className="text-right font-mono text-text-secondary">
                        {s.price != null ? `$${s.price.toFixed(2)}` : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
