/**
 * WebSocket client for real-time updates.
 */

type MessageHandler = (data: unknown) => void

class WSClient {
  private ws: WebSocket | null = null
  private url: string
  private handlers: Map<string, Set<MessageHandler>> = new Map()
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectDelay = 2000
  private maxReconnectDelay = 30000

  constructor() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    this.url = `${protocol}//${window.location.host}/api/v1/ws`
  }

  connect(channels: string[] = ['signals', 'scores', 'refresh']) {
    if (this.ws?.readyState === WebSocket.OPEN) return

    this.ws = new WebSocket(this.url)

    this.ws.onopen = () => {
      console.log('[WS] Connected')
      this.reconnectDelay = 2000
      this.ws?.send(JSON.stringify({ type: 'subscribe', channels }))
    }

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        const msgType = msg.type as string
        const handlers = this.handlers.get(msgType) || new Set()
        const allHandlers = this.handlers.get('*') || new Set()
        handlers.forEach(h => h(msg.data))
        allHandlers.forEach(h => h(msg))
      } catch (e) {
        console.warn('[WS] Parse error:', e)
      }
    }

    this.ws.onclose = () => {
      console.log('[WS] Disconnected, reconnecting...')
      this.scheduleReconnect(channels)
    }

    this.ws.onerror = (e) => {
      console.error('[WS] Error:', e)
    }
  }

  private scheduleReconnect(channels: string[]) {
    if (this.reconnectTimer) return
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, this.maxReconnectDelay)
      this.connect(channels)
    }, this.reconnectDelay)
  }

  on(type: string, handler: MessageHandler) {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, new Set())
    }
    this.handlers.get(type)!.add(handler)
    return () => this.handlers.get(type)?.delete(handler)
  }

  off(type: string, handler: MessageHandler) {
    this.handlers.get(type)?.delete(handler)
  }

  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.ws?.close()
    this.ws = null
  }
}

export const wsClient = new WSClient()
