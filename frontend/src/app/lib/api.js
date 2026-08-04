const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_API_URL || "/api"

export async function apiFetch(path, options = {}) {
  const baseUrl = API_BASE_URL.replace(/\/$/, "")
  const apiPath = path.startsWith("/") ? path : `/${path}`
  return fetch(`${baseUrl}${apiPath}`, options)
}

export async function fetchJson(path, options = {}) {
  const response = await apiFetch(path, {
    cache: "no-store",
    ...options,
  })

  const data = await response.json().catch(() => null)

  if (!response.ok) {
    throw new Error(data?.detail || "Failed to fetch API data")
  }

  return data
}

export async function fetchAnnouncements(filters = {}) {
  const params = new URLSearchParams()

  if (filters.today) {
    params.set("today", "true")
  }

  if (filters.sector) {
    params.set("sector", filters.sector)
  }

  if (filters.startDate) {
    params.set("start_date", filters.startDate)
  }

  if (filters.endDate) {
    params.set("end_date", filters.endDate)
  }

  const query = params.toString()
  return fetchJson(`/announcements/${query ? `?${query}` : ""}`)
}

export async function fetchTrendingAnnouncements({ days = 7, limit = 4 } = {}) {
  const params = new URLSearchParams()
  params.set("days", String(days))
  params.set("limit", String(limit))
  return fetchJson(`/announcements/trending?${params.toString()}`)
}

export async function fetchTickers({ limit = 100, skip = 0 } = {}) {
  const params = new URLSearchParams()
  params.set("skip", String(skip))
  params.set("limit", String(limit))
  return fetchJson(`/tickers/?${params.toString()}`)
}

export async function fetchTickerOverview(symbol) {
  return fetchJson(`/tickers/symbol/${encodeURIComponent(symbol)}/overview`)
}

export async function fetchTickerBriefAside(symbol) {
  return fetchJson(`/tickers/symbol/${encodeURIComponent(symbol)}/brief-aside`)
}

export async function fetchTickerNews(symbol) {
  return fetchJson(`/tickers/symbol/${encodeURIComponent(symbol)}/news-feed`)
}

export async function fetchTickerDeepDive(symbol) {
  return fetchJson(`/tickers/symbol/${encodeURIComponent(symbol)}/deep-dive-timeline`)
}

export async function fetchTickerCategorySentiment(symbol) {
  return fetchJson(`/sentiment/${encodeURIComponent(symbol)}?persist=false`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({}),
  })
}
