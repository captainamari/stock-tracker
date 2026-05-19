/**
 * Layout store — manages widget visibility, grid positions, and presets.
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface WidgetConfig {
  id: string
  title: string
  visible: boolean
  // react-grid-layout position
  x: number
  y: number
  w: number
  h: number
  minW?: number
  minH?: number
}

export type LayoutPreset = 'full' | 'momentum' | 'signals' | 'custom'

const FULL_LAYOUT: WidgetConfig[] = [
  { id: 'market-pulse', title: 'Market Pulse', visible: true, x: 0, y: 0, w: 12, h: 3, minW: 6, minH: 2 },
  { id: 'momentum-heatmap', title: 'Momentum Heatmap', visible: true, x: 0, y: 3, w: 8, h: 7, minW: 4, minH: 4 },
  { id: 'signal-feed', title: 'Signal Feed', visible: true, x: 8, y: 3, w: 4, h: 7, minW: 3, minH: 4 },
  { id: 'position-summary', title: 'Position Summary', visible: true, x: 0, y: 10, w: 7, h: 6, minW: 5, minH: 4 },
  { id: 'score-chart', title: 'Score Trend', visible: true, x: 7, y: 10, w: 5, h: 6, minW: 4, minH: 4 },
]

const MOMENTUM_LAYOUT: WidgetConfig[] = [
  { id: 'market-pulse', title: 'Market Pulse', visible: true, x: 0, y: 0, w: 12, h: 3, minW: 6, minH: 2 },
  { id: 'momentum-heatmap', title: 'Momentum Heatmap', visible: true, x: 0, y: 3, w: 12, h: 8, minW: 6, minH: 5 },
  { id: 'signal-feed', title: 'Signal Feed', visible: false, x: 0, y: 0, w: 4, h: 6, minW: 3, minH: 4 },
  { id: 'position-summary', title: 'Position Summary', visible: true, x: 0, y: 11, w: 12, h: 6, minW: 6, minH: 4 },
  { id: 'score-chart', title: 'Score Trend', visible: true, x: 0, y: 17, w: 12, h: 6, minW: 4, minH: 4 },
]

const SIGNALS_LAYOUT: WidgetConfig[] = [
  { id: 'market-pulse', title: 'Market Pulse', visible: true, x: 0, y: 0, w: 12, h: 3, minW: 6, minH: 2 },
  { id: 'momentum-heatmap', title: 'Momentum Heatmap', visible: false, x: 0, y: 0, w: 8, h: 7, minW: 4, minH: 4 },
  { id: 'signal-feed', title: 'Signal Feed', visible: true, x: 0, y: 3, w: 5, h: 10, minW: 3, minH: 5 },
  { id: 'position-summary', title: 'Position Summary', visible: true, x: 5, y: 3, w: 7, h: 10, minW: 5, minH: 5 },
  { id: 'score-chart', title: 'Score Trend', visible: false, x: 0, y: 0, w: 5, h: 6, minW: 4, minH: 4 },
]

const PRESET_MAP: Record<LayoutPreset, WidgetConfig[]> = {
  full: FULL_LAYOUT,
  momentum: MOMENTUM_LAYOUT,
  signals: SIGNALS_LAYOUT,
  custom: FULL_LAYOUT,
}

interface LayoutState {
  widgets: WidgetConfig[]
  activePreset: LayoutPreset
  panelOpen: boolean

  // Actions
  setPreset: (preset: LayoutPreset) => void
  toggleWidget: (id: string) => void
  updateLayout: (layouts: Array<{ i: string; x: number; y: number; w: number; h: number }>) => void
  setPanelOpen: (open: boolean) => void
  resetLayout: () => void
}

export const useLayoutStore = create<LayoutState>()(
  persist(
    (set, get) => ({
      widgets: FULL_LAYOUT,
      activePreset: 'full',
      panelOpen: false,

      setPreset: (preset) => {
        set({
          widgets: PRESET_MAP[preset] || FULL_LAYOUT,
          activePreset: preset,
        })
      },

      toggleWidget: (id) => {
        const widgets = get().widgets.map(w =>
          w.id === id ? { ...w, visible: !w.visible } : w
        )
        set({ widgets, activePreset: 'custom' })
      },

      updateLayout: (layouts) => {
        const widgets = get().widgets.map(w => {
          const layout = layouts.find(l => l.i === w.id)
          if (layout) {
            return { ...w, x: layout.x, y: layout.y, w: layout.w, h: layout.h }
          }
          return w
        })
        set({ widgets, activePreset: 'custom' })
      },

      setPanelOpen: (open) => set({ panelOpen: open }),

      resetLayout: () => set({ widgets: FULL_LAYOUT, activePreset: 'full' }),
    }),
    {
      name: 'stock-tracker-layout',
    }
  )
)
