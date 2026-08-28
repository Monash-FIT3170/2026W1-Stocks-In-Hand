import { TickerBriefShell } from "../../components/ticker/TickerBriefShell"

const DEPLOYED_TICKERS = ["ANZ", "CBA", "BHP", "WES", "CSL"]

export const dynamicParams = false

export function generateStaticParams() {
  return DEPLOYED_TICKERS.map((symbol) => ({ symbol }))
}

export async function generateMetadata({ params }) {
  const { symbol } = await params
  return { title: `${symbol.toUpperCase()} company brief | StonksInHand` }
}

export default async function TickerLayout({ children, params }) {
  const { symbol } = await params
  return <TickerBriefShell symbol={symbol.toUpperCase()}>{children}</TickerBriefShell>
}
