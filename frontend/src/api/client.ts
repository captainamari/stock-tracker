/**
 * API client for the Stock Tracker backend.
 */

const BASE_URL = '/api/v1'

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const error = await res.text()
    throw new Error(`API Error ${res.status}: ${error}`)
  }
  return res.json()
}

// ── Strategies ──
export const strategiesApi = {
  list: () => fetchJSON<{ strategies: import('../types').Strategy[]; total: number }>(`${BASE_URL}/strategies/`),
  get: (name: string) => fetchJSON<import('../types').Strategy>(`${BASE_URL}/strategies/${name}`),
  run: (name: string, symbols: string[]) =>
    fetchJSON<{ results: Record<string, unknown>; errors: string[] }>(`${BASE_URL}/strategies/${name}/run`, {
      method: 'POST',
      body: JSON.stringify({ symbols }),
    }),
}

// ── Momentum ──
export const momentumApi = {
  scores: (params?: { layer?: string; urgency_min?: string }) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString()
    return fetchJSON<import('../types').MomentumScore[]>(`${BASE_URL}/momentum/scores${qs ? '?' + qs : ''}`)
  },
  heatmap: () => fetchJSON<import('../types').HeatmapData>(`${BASE_URL}/momentum/heatmap`),
  history: (symbol: string, days = 60) =>
    fetchJSON<import('../types').ScoreHistoryPoint[]>(`${BASE_URL}/momentum/history/${symbol}?days=${days}`),
  relative: () => fetchJSON<{ symbol: string; score: number | null; vs_spy: number | null; vs_sector: number | null }[]>(`${BASE_URL}/momentum/relative`),
  refresh: () => fetchJSON<{ status: string; summary: unknown }>(`${BASE_URL}/momentum/refresh`, { method: 'POST' }),
}

// ── Market ──
export const marketApi = {
  overview: () => fetchJSON<import('../types').MarketOverview>(`${BASE_URL}/market/overview`),
  pulse: () => fetchJSON<import('../types').MarketPulse | null>(`${BASE_URL}/market/pulse`),
  pulseHistory: (days = 30) => fetchJSON<import('../types').MarketPulse[]>(`${BASE_URL}/market/pulse/history?days=${days}`),
  sectors: () => fetchJSON<import('../types').SectorOverview[]>(`${BASE_URL}/market/sectors`),
}

// ── Signals ──
export const signalsApi = {
  feed: (params?: { urgency_min?: string; layer?: string; limit?: number }) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString()
    return fetchJSON<import('../types').SignalFeedItem[]>(`${BASE_URL}/signals/feed${qs ? '?' + qs : ''}`)
  },
  recent: (limit = 30) => fetchJSON<unknown[]>(`${BASE_URL}/signals/recent?limit=${limit}`),
  active: () => fetchJSON<unknown[]>(`${BASE_URL}/signals/active`),
}
