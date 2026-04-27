import { useEffect, useRef } from 'react'

/**
 * usePolling — fires `callback` immediately then every `intervalMs` milliseconds.
 *
 * Cleans up the interval when the component unmounts or when dependencies change.
 * The callback is stored in a ref so stale closure issues are avoided.
 *
 * @param {Function} callback - async-safe function to call on each tick
 * @param {number}   intervalMs - polling interval in milliseconds (default: 3000)
 * @param {boolean}  enabled - set false to pause polling (default: true)
 */
export function usePolling(callback, intervalMs = 3000, enabled = true) {
  const callbackRef = useRef(callback)

  // Keep ref up to date without restarting the interval
  useEffect(() => {
    callbackRef.current = callback
  }, [callback])

  useEffect(() => {
    if (!enabled) return

    // Fire immediately on mount / when enabled flips true
    callbackRef.current()

    const id = setInterval(() => {
      callbackRef.current()
    }, intervalMs)

    return () => clearInterval(id)
  }, [intervalMs, enabled])
}
