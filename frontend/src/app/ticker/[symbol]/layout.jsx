const DEPLOYED_TICKERS = ["ANZ", "CBA", "BHP", "WES", "CSL"]

export const dynamicParams = false

export function generateStaticParams() {
  return DEPLOYED_TICKERS.map((symbol) => ({ symbol }))
}

export default function TickerLayout({ children }) {
  return children
}
