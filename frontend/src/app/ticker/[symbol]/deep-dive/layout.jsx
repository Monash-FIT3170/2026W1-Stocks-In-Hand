export async function generateMetadata({ params }) {
  const { symbol } = await params
  return { title: `${symbol.toUpperCase()} deep dive | StonksInHand` }
}

export default function TickerDeepDiveLayout({ children }) {
  return children
}
