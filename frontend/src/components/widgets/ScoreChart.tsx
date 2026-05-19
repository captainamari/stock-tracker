/**
 * Score Chart Widget — Lightweight Charts integration for score history.
 */

import { useEffect, useRef, useState } from 'react'
import { useAppStore } from '../../stores/appStore'
import { momentumApi } from '../../api/client'
import type { ScoreHistoryPoint } from '../../types'

export function ScoreChart() {
  const { selectedSymbol, momentumScores } = useAppStore()
  const [history, setHistory] = useState<ScoreHistoryPoint[]>([])
  const [chartSymbol, setChartSymbol] = useState<string>('NVDA')
  const canvasRef = useRef<HTMLCanvasElement>(null)

  // Use selected symbol or default
  const activeSymbol = selectedSymbol || chartSymbol

  // Fetch history when symbol changes
  useEffect(() => {
    const sym = activeSymbol
    if (!sym) return
    momentumApi.history(sym, 30).then(setHistory).catch(console.error)
  }, [activeSymbol])

  // Simple canvas chart rendering
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || history.length === 0) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    canvas.width = rect.width * dpr
    canvas.height = rect.height * dpr
    ctx.scale(dpr, dpr)

    const w = rect.width
    const h = rect.height
    const padding = { top: 20, bottom: 25, left: 35, right: 10 }
    const chartW = w - padding.left - padding.right
    const chartH = h - padding.top - padding.bottom

    // Clear
    ctx.fillStyle = '#111827'
    ctx.fillRect(0, 0, w, h)

    // Data
    const points = history.filter(p => p.score != null) as { date: string; score: number }[]
    if (points.length < 2) return

    const minScore = Math.min(...points.map(p => p.score)) - 5
    const maxScore = Math.max(...points.map(p => p.score)) + 5
    const scoreRange = maxScore - minScore || 1

    // Grid lines
    ctx.strokeStyle = '#1e293b'
    ctx.lineWidth = 0.5
    const levels = [40, 50, 60, 70]
    levels.forEach(level => {
      if (level >= minScore && level <= maxScore) {
        const y = padding.top + chartH * (1 - (level - minScore) / scoreRange)
        ctx.beginPath()
        ctx.moveTo(padding.left, y)
        ctx.lineTo(w - padding.right, y)
        ctx.stroke()
        // Label
        ctx.fillStyle = '#64748b'
        ctx.font = '9px JetBrains Mono'
        ctx.textAlign = 'right'
        ctx.fillText(level.toString(), padding.left - 4, y + 3)
      }
    })

    // Draw line
    ctx.beginPath()
    ctx.strokeStyle = '#3b82f6'
    ctx.lineWidth = 2
    ctx.lineJoin = 'round'

    points.forEach((p, i) => {
      const x = padding.left + (i / (points.length - 1)) * chartW
      const y = padding.top + chartH * (1 - (p.score - minScore) / scoreRange)
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    })
    ctx.stroke()

    // Fill area
    const lastX = padding.left + chartW
    const lastY = padding.top + chartH
    ctx.lineTo(lastX, lastY)
    ctx.lineTo(padding.left, lastY)
    ctx.closePath()
    const gradient = ctx.createLinearGradient(0, padding.top, 0, lastY)
    gradient.addColorStop(0, 'rgba(59, 130, 246, 0.2)')
    gradient.addColorStop(1, 'rgba(59, 130, 246, 0)')
    ctx.fillStyle = gradient
    ctx.fill()

    // Current score dot
    const last = points[points.length - 1]!
    const lx = padding.left + chartW
    const ly = padding.top + chartH * (1 - (last.score - minScore) / scoreRange)
    ctx.beginPath()
    ctx.arc(lx, ly, 4, 0, Math.PI * 2)
    ctx.fillStyle = last.score >= 60 ? '#10b981' : last.score >= 40 ? '#f59e0b' : '#ef4444'
    ctx.fill()

    // X-axis dates
    ctx.fillStyle = '#64748b'
    ctx.font = '8px JetBrains Mono'
    ctx.textAlign = 'center'
    const step = Math.max(1, Math.floor(points.length / 5))
    for (let i = 0; i < points.length; i += step) {
      const x = padding.left + (i / (points.length - 1)) * chartW
      const dateStr = points[i]!.date.slice(5) // MM-DD
      ctx.fillText(dateStr, x, h - 5)
    }
  }, [history])

  // Available symbols for selection
  const availableSymbols = momentumScores
    .filter(s => s.layer === 'stock')
    .map(s => s.symbol)

  return (
    <div className="widget-card">
      <div className="widget-header">
        <span className="widget-title">Score Trend</span>
        <select
          value={activeSymbol}
          onChange={e => setChartSymbol(e.target.value)}
          className="text-2xs bg-surface-3 border-none rounded px-1.5 py-0.5 text-text-primary outline-none"
        >
          {availableSymbols.length > 0 ? (
            availableSymbols.map(s => <option key={s} value={s}>{s}</option>)
          ) : (
            <option value="NVDA">NVDA</option>
          )}
        </select>
      </div>
      <div className="widget-body p-0">
        <canvas
          ref={canvasRef}
          className="w-full h-44"
          style={{ display: 'block' }}
        />
      </div>
    </div>
  )
}
