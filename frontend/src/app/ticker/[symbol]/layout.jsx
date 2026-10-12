import { CompanyData } from "../../components/company/CompanyData"
import { CompanyWorkspace } from "../../components/company/CompanyWorkspace"

const DEPLOYED_TICKERS = [
  "ANZ",
  "BHP",
  "CBA",
  "COL",
  "COH",
  "CSL",
  "MQG",
  "ORG",
  "RIO",
  "TCL",
  "TLS",
  "WDS",
  "WES",
]

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
