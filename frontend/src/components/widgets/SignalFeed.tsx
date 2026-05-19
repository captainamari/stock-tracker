/**
 * Signal Feed Widget — Real-time signal list sorted by urgency.
 */

import { useAppStore } from '../../stores/appStore'
import { clsx } from 'clsx'
import type { SignalFeedItem } from '../../types'

const urgencyConfig: Record<string, { badge: string; border: string; icon: string }> = {
  CRITICAL: { badge: 'badge-red', border: 'border-l-accent-red', icon: '🔴' },
  HIGH: { badge: 'badge-orange', border: 'border-l-accent-orange', icon: '🔶' },
  MEDIUM: { badge: 'badge-yellow', border: 'border-l-accent-yellow', icon: '🟡' },
  LOW: { badge: 'badge-blue', border: 'border-l-accent-blue', icon: '🔵' },
  NONE: { badge: 'badge-neutral', border: 'border-l-surface-3', icon: '⚪' },
}

function SignalItem({ item }: { item: SignalFeedItem }) {
  const config = urgencyConfig[item.urgency] || urgencyConfig.NONE

  return (
    <div className={clsx('border-l-2 pl-2 py-1.5', config.border)}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="text-xs">{config.icon}</span>
          <span className="text-xs font-semibold text-text-primary">{item.symbol}</span>
          {item.score != null && (
            <span className="text-2xs font-mono text-text-muted">{item.score.toFixed(1)}</span>
          )}
        </div>
        {item.position_advice != null && (
          <span className={clsx('badge', item.position_advice === 0 ? 'badge-red' : item.position_advice <= 30 ? 'badge-orange' : 'badge-neutral')}>
            {item.position_advice}%
          </span>
        )}
      </div>
      <p className="text-2xs text-text-secondary mt-0.5 line-clamp-1">{item.message}</p>
      {item.price != null && (
        <div className="text-2xs font-mono text-text-muted mt-0.5">
          ${item.price.toFixed(2)}
          {item.daily_change_pct != null && (
            <span className={clsx('ml-1', item.daily_change_pct >= 0 ? 'text-accent-green' : 'text-accent-red')}>
              {item.daily_change_pct >= 0 ? '+' : ''}{item.daily_change_pct.toFixed(2)}%
            </span>
          )}
        </div>
      )}
    </div>
  )
}

export function SignalFeed() {
  const { signalFeed } = useAppStore()

  return (
    <div className="widget-card h-full">
      <div className="widget-header">
        <span className="widget-title">Signal Feed</span>
        <span className={clsx('badge', signalFeed.length > 0 ? 'badge-red' : 'badge-neutral')}>
          {signalFeed.length}
        </span>
      </div>
      <div className="widget-body space-y-2 max-h-80 overflow-y-auto">
        {signalFeed.length === 0 ? (
          <div className="text-center text-text-muted text-sm py-4">No active signals</div>
        ) : (
          signalFeed.map((item, i) => <SignalItem key={`${item.symbol}-${i}`} item={item} />)
        )}
      </div>
    </div>
  )
}
