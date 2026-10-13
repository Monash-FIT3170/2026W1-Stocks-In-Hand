// Generated from the backend ticker catalogue: run `python -m tools.sync_tickers` in backend/.
import DEPLOYED_TICKERS from "../../ticker/tickers.json"

const COMPANY_TICKERS = new Set(DEPLOYED_TICKERS)

export function companyRoute(ticker) {
  const symbol = String(ticker || "").toUpperCase()
  return COMPANY_TICKERS.has(symbol) ? `/ticker/${symbol}` : null
}

export function originalUrl(value) {
  if (typeof value !== "string") return null
  try {
    const url = new URL(value)
    return ["https:", "http:"].includes(url.protocol) ? url.href : null
  } catch { return null }
}

export function meaningfulText(value, title = "") {
  if (typeof value !== "string") return ""
  const text = value.trim()
  if (!text || text.toLowerCase() === String(title).trim().toLowerCase()) return ""
  const pending = ["Summary pending.", "No change summary available yet.", "No impact summary available yet.", "No investment impact summary available yet."]
  return pending.includes(text) ? "" : text
}

export function sourceKind(type = "") {
  const value = String(type).toLowerCase()
  if (/reddit|bluesky|mastodon|discussion|hotcopper|blog/.test(value)) return "Public discussion"
  if (/news|publisher/.test(value)) return "Publisher news"
  if (/asx|filing|announcement/.test(value)) return "Official filing"
  return "Source record"
}

export function recordSources(item) {
  const sources = Array.isArray(item.sources) ? item.sources.filter(Boolean) : []
  const primary = originalUrl(item.url) || sources.map((source) => originalUrl(source.url)).find(Boolean) || null
  const seen = new Set(primary ? [primary] : [])
  const additional = sources.filter((source) => {
    const url = originalUrl(source.url)
    if (!url || seen.has(url)) return false
    seen.add(url)
    return true
  })
  return { primary, additional }
}

export function groupByPublicationDate(items) {
  const groups = new Map()
  const formatter = new Intl.DateTimeFormat("en-AU", { day: "numeric", month: "long", year: "numeric", timeZone: "Australia/Sydney" })
  for (const item of items) {
    const date = item.published_at ? new Date(item.published_at) : null
    const label = date && !Number.isNaN(date.getTime()) ? formatter.format(date) : "Date unavailable"
    if (!groups.has(label)) groups.set(label, { label, items: [] })
    groups.get(label).items.push(item)
  }
  return [...groups.values()]
}
