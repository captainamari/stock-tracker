/**
 * TypeScript type definitions for the trading platform API.
 */

export interface Strategy {
  name: string
  display_name: string
  version: string
  layer: 'market' | 'sector' | 'stock'
  description: string
  requires_market_data: boolean
  requires_sector_data: boolean
  min_data_points: number
  config_schema: Record<string, unknown>
}

export interface MomentumScore {
  symbol: string
  date: string
  layer: 'market' | 'sector' | 'stock'
  final_score: number | null
  regime: string | null
  delta_1d: number | null
  delta_5d: number | null
  consecutive_above_65: number
  consecutive_above_70: number
  consecutive_below_60: number
  signals: string[]
  position_advice: number | null
  urgency: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE'
  relative_strength: {
    vs_spy?: number | null
    vs_sector?: number | null
    sector_name?: string | null
    alpha?: boolean | null
  }
  price: number | null
  daily_change_pct: number | null
}

export interface HeatmapItem {
  symbol: string
  name: string
  layer: string
  score: number | null
  regime: string | null
  delta_1d: number | null
  urgency: string
  sector?: string | null
}

export interface HeatmapData {
  market: HeatmapItem[]
  sectors: HeatmapItem[]
  stocks: HeatmapItem[]
  date: string
}

export interface MarketPulse {
  date: string
  regime: string
  composite_score: number
  component_scores: Record<string, number>
  spy_price: number | null
  vix_value: number | null
  distribution_days: Record<string, unknown>
}

export interface MarketOverview {
  pulse: MarketPulse | null
  sentiment: {
    spy: { symbol: string; score: number | null; regime: string | null; delta_1d: number | null; price: number | null; daily_change_pct: number | null } | null
    qqq: { symbol: string; score: number | null; regime: string | null; delta_1d: number | null; price: number | null; daily_change_pct: number | null } | null
    mood: string
    tech_vs_broad: number | null
  }
  sectors: SectorOverview[]
  date: string
}

export interface SectorOverview {
  sector_key: string
  sector_name: string
  etf_symbol: string | null
  score: number | null
  regime: string | null
  delta_1d: number | null
  stocks: string[]
}

export interface SignalFeedItem {
  symbol: string
  strategy: string
  urgency: string
  signal_type: string
  message: string
  score: number | null
  position_advice: number | null
  price: number | null
  daily_change_pct: number | null
  date: string
  layer: string
}

export interface ScoreHistoryPoint {
  date: string
  score: number | null
  regime?: string | null
}

export type Urgency = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE'
export type Regime = 'STRONG_TREND' | 'STRONG' | 'NEUTRAL' | 'WEAK' | 'N/A'
