const PREVIEW_TICKERS = [
  { id: "preview-bhp", symbol: "BHP", company_name: "BHP Group", sector: "Materials", industry: "Diversified Metals & Mining", exchange: "ASX", market_cap: null, is_preview: true },
  { id: "preview-csl", symbol: "CSL", company_name: "CSL Limited", sector: "Health Care", industry: "Biotechnology", exchange: "ASX", market_cap: null, is_preview: true },
  { id: "preview-cba", symbol: "CBA", company_name: "Commonwealth Bank", sector: "Financials", industry: "Diversified Banks", exchange: "ASX", market_cap: null, is_preview: true },
  { id: "preview-wes", symbol: "WES", company_name: "Wesfarmers", sector: "Consumer Discretionary", industry: "Diversified Retail", exchange: "ASX", market_cap: null, is_preview: true },
  { id: "preview-xro", symbol: "XRO", company_name: "Xero", sector: "Technology", industry: "Application Software", exchange: "ASX", market_cap: null, is_preview: true },
  { id: "preview-wds", symbol: "WDS", company_name: "Woodside Energy", sector: "Energy", industry: "Oil & Gas Exploration", exchange: "ASX", market_cap: null, is_preview: true },
]

const ANNOUNCEMENT_BLUEPRINTS = [
  { ticker: "BHP", sector: "Materials", tag: "ASX filing", title: "Operational update published", about: "An illustrative operational update used to demonstrate the market-feed layout.", changed: "The sample groups production commentary and guidance context into a concise research summary.", matters: "It shows how material operating signals can be scanned before opening the original filing." },
  { ticker: "CSL", sector: "Health Care", tag: "Presentation", title: "Research and development presentation lodged", about: "An illustrative investor presentation covering a company research programme.", changed: "The preview highlights the programme context and the type of milestone discussed.", matters: "It demonstrates how longer presentations can be reduced to verifiable points of interest." },
  { ticker: "CBA", sector: "Financials", tag: "Investor update", title: "Investor presentation added to the market feed", about: "A sample investor update prepared only for this local interface preview.", changed: "The card separates the subject, reported change, and research significance.", matters: "The three-part structure helps readers decide whether the source deserves a closer look." },
  { ticker: "WES", sector: "Consumer Discretionary", tag: "Trading update", title: "Trading update received", about: "An illustrative trading update across a diversified retail portfolio.", changed: "The preview surfaces the business areas discussed without asserting live financial figures.", matters: "It demonstrates how mixed divisional commentary remains readable on a single card." },
  { ticker: "XRO", sector: "Technology", tag: "Annual report", title: "Annual report available for review", about: "A sample annual-report record showing how formal company material appears in the feed.", changed: "The interface keeps the source type, timestamp, and company symbol close to the summary.", matters: "Clear provenance makes it easier to distinguish official records from public discussion." },
  { ticker: "WDS", sector: "Energy", tag: "Project update", title: "Project update published", about: "An illustrative project update used to populate the local design preview.", changed: "The sample demonstrates a concise explanation without inventing project metrics.", matters: "It shows how readers can identify the nature of an update before inspecting the source." },
  { ticker: "BHP", sector: "Materials", tag: "Publisher news", title: "Publisher coverage added", about: "An illustrative publisher record linked to the company research workspace.", changed: "The source label differentiates publisher context from an official ASX filing.", matters: "Separating source types helps readers apply the right level of confidence." },
  { ticker: "CSL", sector: "Health Care", tag: "Public discussion", title: "Discussion activity detected", about: "A sample public-discussion signal shown separately from company-issued material.", changed: "The card identifies discussion as a distinct source type rather than a verified filing.", matters: "The distinction helps prevent market conversation from being read as company fact." },
]

function previewPublishedAt(index) {
  const date = new Date(Date.now() - index * 22 * 60 * 60 * 1000)
  date.setMinutes(18 + index * 3, 0, 0)
  return date.toISOString()
}

function createPreviewAnnouncements() {
  return ANNOUNCEMENT_BLUEPRINTS.map((item, index) => {
    const publishedAt = previewPublishedAt(index)
    const companyUrl = `https://www.asx.com.au/markets/company/${item.ticker.toLowerCase()}`
    return {
      ...item,
      id: `preview-announcement-${index + 1}`,
      is_preview: true,
      published_at: publishedAt,
      source_label: "Open example company page",
      sources: [{ label: "Example source", published_at: publishedAt, title: `${item.ticker} company page`, url: companyUrl }],
      url: companyUrl,
    }
  })
}

export function isLocalPreviewHost() {
  if (typeof window === "undefined") return false
  return ["localhost", "127.0.0.1", "0.0.0.0"].includes(window.location.hostname)
}

export function getPreviewTickers({ limit = 100, skip = 0 } = {}) {
  return PREVIEW_TICKERS.slice(skip, skip + limit)
}

export function getPreviewAnnouncements(filters = {}) {
  const start = filters.startDate || ""
  const end = filters.endDate || ""
  const today = new Date().toISOString().slice(0, 10)
  const filtered = createPreviewAnnouncements().filter((item) => {
    const itemDate = item.published_at.slice(0, 10)
    if (filters.today && itemDate !== today) return false
    if (filters.sector && item.sector !== filters.sector) return false
    if (start && itemDate < start) return false
    if (end && itemDate > end) return false
    return true
  })
  const offset = Number(filters.offset) || 0
  const limit = Number(filters.limit) || filtered.length
  return filtered.slice(offset, offset + limit)
}

export function getPreviewTrending({ limit = 4 } = {}) {
  return [
    { symbol: "BHP", announcement_count: 3, is_preview: true },
    { symbol: "CSL", announcement_count: 2, is_preview: true },
    { symbol: "CBA", announcement_count: 2, is_preview: true },
    { symbol: "WES", announcement_count: 1, is_preview: true },
    { symbol: "XRO", announcement_count: 1, is_preview: true },
  ].slice(0, limit)
}
