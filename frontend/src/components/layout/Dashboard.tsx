/**
 * Dashboard layout — Grid-based widget arrangement.
 */

import { MarketPulseWidget } from '../widgets/MarketPulse'
import { MomentumHeatmap } from '../widgets/MomentumHeatmap'
import { SignalFeed } from '../widgets/SignalFeed'
import { PositionSummary } from '../widgets/PositionSummary'
import { ScoreChart } from '../widgets/ScoreChart'

export function Dashboard() {
  return (
    <div className="flex-1 overflow-auto p-3 grid grid-cols-12 gap-3 auto-rows-min">
      {/* Row 1: Market Pulse (full width) */}
      <div className="col-span-12">
        <MarketPulseWidget />
      </div>

      {/* Row 2: Heatmap (8 cols) + Signal Feed (4 cols) */}
      <div className="col-span-12 lg:col-span-8">
        <MomentumHeatmap />
      </div>
      <div className="col-span-12 lg:col-span-4">
        <SignalFeed />
      </div>

      {/* Row 3: Position Summary (7 cols) + Score Chart (5 cols) */}
      <div className="col-span-12 lg:col-span-7">
        <PositionSummary />
      </div>
      <div className="col-span-12 lg:col-span-5">
        <ScoreChart />
      </div>
    </div>
  )
}
