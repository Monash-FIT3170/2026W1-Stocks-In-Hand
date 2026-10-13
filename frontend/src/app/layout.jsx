import { AppFrame } from "./components/layout/AppFrame"
import localFont from "next/font/local"
import "./tokens.css"

const inter = localFont({ src: "./fonts/InterVariable.woff2", variable: "--font-inter", weight: "100 900", display: "swap" })

export const metadata = {
  title: "StonksInHand — sourced ASX briefs",
  description: "Plain-English ASX company briefs backed by linked source material.",
}

export default function Layout({ children }) {
  return (
    <html lang="en-AU" className={inter.variable}>
      <body>
        <script type="application/json" id="visual-direction" dangerouslySetInnerHTML={{ __html: JSON.stringify({
          reference: "user-pinned-quartr-2026-10-13",
          thesis: "Wide source-first compositions with distinct reading, evidence and control regions.",
          ownWorld: "Inter Variable, near-black ink, neutral stone context, cobalt interaction, restrained rectangular controls.",
          story: "Find an ASX company or update, understand its stored research, and inspect original evidence.",
          firstViewport: "Aligned 1360px frame; composed introduction and product exhibit on home; clear identity and analysis/evidence columns in research.",
          form: "User-approved Quartr reference and twenty-route design plan; code-led implementation.",
          finish: "unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance",
        }) }} />
        <AppFrame>{children}</AppFrame>
      </body>
    </html>
  )
}
