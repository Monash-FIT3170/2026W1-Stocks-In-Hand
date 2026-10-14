export function safeSourceUrl(value) {
  if (typeof value !== "string") return null
  try { const url = new URL(value); return ["http:", "https:"].includes(url.protocol) ? url.href : null } catch { return null }
}

export function displayDate(value) {
  if (!value) return "Date unavailable"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "Date unavailable" : new Intl.DateTimeFormat("en-AU", { day: "numeric", month: "short", year: "numeric" }).format(date)
}

export function percentage(value) { return typeof value === "number" && Number.isFinite(value) ? `${Math.round(value * 100)}%` : "Unavailable" }

export function recordKind(record) {
  const type = String(record?.source_type || "").toLowerCase()
  if (["discussion", "reddit", "hotcopper", "bluesky", "mastodon", "blog"].some((name) => type.includes(name))) return "Public discussion"
  if (type.includes("news") || type.includes("publisher")) return "Publisher news"
  if (type.includes("filing") || type.includes("asx") || type.includes("announcement")) return "Official filing"
  return record?.source_type || "Source record"
}

// Keep the server order as chronology: the API supplies display dates, not stable timestamps.
export function filterRecords(records, query, kind, order = "newest") {
  const needle = query.trim().toLowerCase()
  const result = records.map((record, index) => ({ record, id: index })).filter(({ record }) => {
    const text = [record.title, record.source_name, record.about, record.changed, record.matters, record.tag].filter(Boolean).join(" ").toLowerCase()
    return (!needle || text.includes(needle)) && (kind === "all" || recordKind(record) === kind)
  })
  return order === "oldest" ? result.reverse() : result
}

export function selectRecord(records, selectedId) { return records.find((item) => item.id === selectedId) || records[0] || null }

export function hasResearchText(value) {
  return typeof value === "string" && value.trim() !== ""
}

export function modelName(value) {
  if (!value) return "Unavailable"
  const name = String(value).split(/[\\/]/).filter(Boolean).pop()
  return name?.toLowerCase() === "finbert" ? "FinBERT" : name || "Unavailable"
}

export function publisherLabel(value) {
  return /^asx[ _]announcement$/i.test(String(value || "")) ? "ASX announcement" : value
}
