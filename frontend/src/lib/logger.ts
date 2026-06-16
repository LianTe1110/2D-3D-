export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

export interface LogEntry {
  id: string
  level: LogLevel
  tag: string
  message: string
  data?: any
  time: number
}

const LEVEL_PRIORITY: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
}

let currentLevel: LogLevel = import.meta.env.DEV ? 'debug' : 'warn'
const listeners = new Set<(entry: LogEntry) => void>()
const MAX_LOGS = 200
const logBuffer: LogEntry[] = []

function emit(level: LogLevel, tag: string, message: string, data?: any) {
  if (LEVEL_PRIORITY[level] < LEVEL_PRIORITY[currentLevel]) return

  const entry: LogEntry = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    level,
    tag,
    message,
    data,
    time: Date.now(),
  }

  logBuffer.push(entry)
  if (logBuffer.length > MAX_LOGS) logBuffer.shift()

  // 也输出到 console
  const fn = level === 'error' ? console.error : level === 'warn' ? console.warn : level === 'debug' ? console.debug : console.info
  fn(`[${tag}] ${message}`, data !== undefined ? data : '')

  listeners.forEach((fn) => fn(entry))
}

export const logger = {
  debug: (tag: string, msg: string, data?: any) => emit('debug', tag, msg, data),
  info: (tag: string, msg: string, data?: any) => emit('info', tag, msg, data),
  warn: (tag: string, msg: string, data?: any) => emit('warn', tag, msg, data),
  error: (tag: string, msg: string, data?: any) => emit('error', tag, msg, data),

  getLogs: () => [...logBuffer],
  clear: () => { logBuffer.length = 0; listeners.forEach((fn) => fn({ id: 'clear', level: 'info', tag: 'logger', message: 'cleared', time: Date.now() })) },
  subscribe: (fn: (entry: LogEntry) => void) => { listeners.add(fn); return () => listeners.delete(fn) },
  setLevel: (level: LogLevel) => { currentLevel = level },
}
