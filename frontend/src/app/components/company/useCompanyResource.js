"use client"

import { useCallback, useEffect, useState } from "react"

export function useCompanyResource(fetcher, symbol, enabled = true) {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState({ data: null, isLoading: true, error: "" })
  useEffect(() => {
    let cancelled = false
    setState({ data: null, isLoading: true, error: "" })
    if (!enabled) return () => { cancelled = true }
    fetcher(symbol).then((data) => {
      if (!cancelled) setState({ data, isLoading: false, error: "" })
    }).catch((error) => {
      if (!cancelled) setState({ data: null, isLoading: false, error: error.message || "This data could not be loaded." })
    })
    return () => { cancelled = true }
  }, [fetcher, symbol, enabled, attempt])
  const retry = useCallback(() => setAttempt((current) => current + 1), [])
  return { ...state, retry }
}
