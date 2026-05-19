/**
 * Main Application Component.
 */

import { useEffect } from 'react'
import { Header } from './components/layout/Header'
import { Dashboard } from './components/layout/Dashboard'
import { useAppStore } from './stores/appStore'
import { wsClient } from './api/websocket'

export default function App() {
  const { fetchAll, fetchMomentum, fetchSignals } = useAppStore()

  // Initial data fetch
  useEffect(() => {
    fetchAll()
  }, [fetchAll])

  // WebSocket connection
  useEffect(() => {
    wsClient.connect(['signals', 'scores', 'refresh'])

    wsClient.on('signal', () => {
      fetchSignals()
    })

    wsClient.on('score_update', () => {
      fetchMomentum()
    })

    return () => wsClient.disconnect()
  }, [fetchMomentum, fetchSignals])

  // Auto-refresh every 5 minutes
  useEffect(() => {
    const timer = setInterval(fetchAll, 5 * 60 * 1000)
    return () => clearInterval(timer)
  }, [fetchAll])

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <Header />
      <Dashboard />
    </div>
  )
}
