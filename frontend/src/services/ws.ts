import type { WSMessage } from '@/types'
import { logger } from '@/lib/logger'

type WSHandler = (msg: WSMessage) => void
type DisconnectCallback = () => void
type ReconnectCallback = () => void  // WS 重连成功回调

class WebSocketClient {
  private ws: WebSocket | null = null
  private handler: WSHandler | null = null
  private onDisconnect: DisconnectCallback | null = null
  private onReconnect: ReconnectCallback | null = null  // 新增
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private url = ''
  private userId = ''
  private isConnected = false

  connect(userId: string, onMessage: WSHandler, onDisconnect?: DisconnectCallback, onReconnect?: ReconnectCallback) {
    this.disconnect()
    this.handler = onMessage
    this.onDisconnect = onDisconnect ?? null
    this.onReconnect = onReconnect ?? null
    this.userId = userId

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    this.url = `${protocol}//${window.location.host}/api/v1/ws?user_id=${userId}`
    logger.info('ws', `Connecting to ${this.url}`)
    this.ws = new WebSocket(this.url)

    this.ws.onopen = () => {
      const wasDisconnected = !this.isConnected  // 是否为重连（之前断开过）
      this.isConnected = true
      logger.info('ws', wasDisconnected ? 'Reconnected' : 'Connected')
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer)
        this.reconnectTimer = null
      }
      // 重连成功时通知外部同步状态
      if (wasDisconnected && this.onReconnect) {
        this.onReconnect()
      }
    }

    this.ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data)
        logger.debug('ws', `Message: ${msg.type}`, msg.data)
        this.handler?.(msg)
      } catch {
        // pong or non-JSON, ignore
      }
    }

    this.ws.onclose = () => {
      this.isConnected = false
      logger.warn('ws', 'Disconnected')
      // 通知外部 WS 已断开，触发降级轮询
      this.onDisconnect?.()
      // 自动重连
      this.reconnectTimer = setTimeout(() => {
        if (this.handler) {
          this.connect(this.userId, this.handler, this.onDisconnect ?? undefined)
        }
      }, 3000)
    }

    this.ws.onerror = (err) => {
      logger.error('ws', 'Connection error', err)
    }

    this.startHeartbeat()
  }

  private startHeartbeat() {
    const interval = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send('ping')
      } else {
        clearInterval(interval)
      }
    }, 30000)
  }

  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.onclose = null  // 防止触发 onDisconnect 回调
      this.ws.close()
      this.ws = null
    }
    this.handler = null
    this.onDisconnect = null
    this.isConnected = false
    logger.info('ws', 'Disconnected')
  }

  get connected() {
    return this.isConnected
  }
}

export const wsClient = new WebSocketClient()
