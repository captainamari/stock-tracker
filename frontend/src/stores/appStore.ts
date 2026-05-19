/**
 * Global application store using Zustand.
 */

import { create } from 'zustand'
import type { MarketOverview, MomentumScore, HeatmapData, SignalFeedItem } from '../types'
import { marketApi, momentumApi, signalsApi } from '../api/client'

interface AppState {
  // Data
  marketOverview: MarketOverview | null
  momentumScores: MomentumScore[]
  heatmap: HeatmapData | null
  signalFeed: SignalFeedItem[]
  
  // UI state
  loading: boolean
  lastUpdate: string | null
  selectedSymbol: string | null
  
  // Actions
  fetchAll: () => Promise<void>
  fetchMarket: () => Promise<void>
  fetchMomentum: () => Promise<void>
  fetchSignals: () => Promise<void>
  setSelectedSymbol: (symbol: string | null) => void
}

export const useAppStore = create<AppState>((set) => ({
  marketOverview: null,
  momentumScores: [],
  heatmap: null,
  signalFeed: [],
  loading: false,
  lastUpdate: null,
  selectedSymbol: null,

  fetchAll: async () => {
    set({ loading: true })
    try {
      const [market, scores, heatmap, signals] = await Promise.all([
        marketApi.overview(),
        momentumApi.scores(),
        momentumApi.heatmap(),
        signalsApi.feed({ limit: 50 }),
      ])
      set({
        marketOverview: market,
        momentumScores: scores,
        heatmap: heatmap,
        signalFeed: signals,
        lastUpdate: new Date().toISOString(),
        loading: false,
      })
    } catch (e) {
      console.error('Failed to fetch data:', e)
      set({ loading: false })
    }
  },

  fetchMarket: async () => {
    try {
      const market = await marketApi.overview()
      set({ marketOverview: market })
    } catch (e) {
      console.error('Failed to fetch market:', e)
    }
  },

  fetchMomentum: async () => {
    try {
      const [scores, heatmap] = await Promise.all([
        momentumApi.scores(),
        momentumApi.heatmap(),
      ])
      set({ momentumScores: scores, heatmap })
    } catch (e) {
      console.error('Failed to fetch momentum:', e)
    }
  },

  fetchSignals: async () => {
    try {
      const signals = await signalsApi.feed({ limit: 50 })
      set({ signalFeed: signals })
    } catch (e) {
      console.error('Failed to fetch signals:', e)
    }
  },

  setSelectedSymbol: (symbol) => set({ selectedSymbol: symbol }),
}))
