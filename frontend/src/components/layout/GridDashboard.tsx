/**
 * Grid Dashboard — Draggable/resizable layout using react-grid-layout.
 */

import { useMemo } from 'react'
import GridLayout from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import { useLayoutStore } from '../../stores/layoutStore'
import { MarketPulseWidget } from '../widgets/MarketPulse'
import { MomentumHeatmap } from '../widgets/MomentumHeatmap'
import { SignalFeed } from '../widgets/SignalFeed'
import { PositionSummary } from '../widgets/PositionSummary'
import { ScoreChart } from '../widgets/ScoreChart'

const WIDGET_COMPONENTS: Record<string, React.FC> = {
  'market-pulse': MarketPulseWidget,
  'momentum-heatmap': MomentumHeatmap,
  'signal-feed': SignalFeed,
  'position-summary': PositionSummary,
  'score-chart': ScoreChart,
}

export function GridDashboard() {
  const { widgets, updateLayout } = useLayoutStore()

  const visibleWidgets = useMemo(
    () => widgets.filter(w => w.visible),
    [widgets]
  )

  const layout = useMemo(
    () => visibleWidgets.map(w => ({
      i: w.id,
      x: w.x,
      y: w.y,
      w: w.w,
      h: w.h,
      minW: w.minW || 2,
      minH: w.minH || 2,
    })),
    [visibleWidgets]
  )

  const handleLayoutChange = (newLayout: GridLayout.Layout[]) => {
    updateLayout(newLayout.map(l => ({ i: l.i, x: l.x, y: l.y, w: l.w, h: l.h })))
  }

  return (
    <div className="flex-1 overflow-auto p-2">
      <GridLayout
        className="layout"
        layout={layout}
        cols={12}
        rowHeight={36}
        width={1200}
        onLayoutChange={handleLayoutChange}
        draggableHandle=".widget-header"
        isResizable={true}
        isDraggable={true}
        compactType="vertical"
        margin={[8, 8]}
      >
        {visibleWidgets.map(w => {
          const Component = WIDGET_COMPONENTS[w.id]
          if (!Component) return null
          return (
            <div key={w.id} className="overflow-hidden">
              <Component />
            </div>
          )
        })}
      </GridLayout>
    </div>
  )
}
