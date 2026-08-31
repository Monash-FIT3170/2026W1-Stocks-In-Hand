import { AppFrame } from "./components/layout/AppFrame"

export const metadata = {
  title: "StonksInHand — sourced ASX briefs",
  description: "Plain-English ASX company briefs backed by linked source material.",
}

export default function Layout({ children }) {
  return (
    <html lang="en-AU">
      <body style={{ background: "#fbfcfc", color: "#101214", margin: 0 }}>
        <AppFrame>{children}</AppFrame>
      </body>
    </html>
  )
}
