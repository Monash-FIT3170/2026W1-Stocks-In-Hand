export async function generateMetadata({ params }) {
  const { symbol } = await params
  return { title: `${symbol.toUpperCase()} news | StonksInHand` }
}

export default function TickerNewsLayout({ children }) {
  return children
}
