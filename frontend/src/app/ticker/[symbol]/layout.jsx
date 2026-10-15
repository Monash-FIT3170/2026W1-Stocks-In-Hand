import { CompanyData } from "../../components/company/CompanyData"
import { CompanyWorkspace } from "../../components/company/CompanyWorkspace"
// Generated from the backend ticker catalogue: run `python -m tools.sync_tickers` in backend/.
import DEPLOYED_TICKERS from "../tickers.json"

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
  return <CompanyData key={symbol.toUpperCase()} symbol={symbol.toUpperCase()}><CompanyWorkspace>{children}</CompanyWorkspace></CompanyData>
}
