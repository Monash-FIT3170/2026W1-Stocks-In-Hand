"use client"
import { useState } from "react"
import React from "react"

export default function Home() {
  const [text, setText] = useState("")
  const [result, setResult] = useState<{label:string,score:number}|null>(null)
  const [loading, setLoading] = useState(false)
  const [headlines, setHeadlines] = useState<string[]>([])

  async function analyse() {
    setLoading(true)
    const res = await fetch("/api/analyse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    })
    setResult(await res.json())
    setLoading(false)
  }

  async function fetchHeadlines() {
    const res = await fetch("/api/headlines")
    setHeadlines(await res.json())
  }

  const colour = result?.label === "positive" ? "#22c55e" : result?.label === "negative" ? "#ef4444" : "#94a3b8"

  return (
    <main style={{ maxWidth: 600, margin: "80px auto", padding: "0 24px" }}>
      <h1 style={{ fontSize: 24, fontWeight: 800 }}>StonksInHand spike</h1>
      <p style={{ color: "#64748b", fontSize: 13 }}>Next.js → FastAPI → FinBERT → PostgreSQL</p>

      <textarea
        rows={4}
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder="Paste a news headline or ASX announcement..."
        style={{ width: "100%", marginTop: 24, padding: 12, background: "#1e2130", border: "1px solid #2d3148", borderRadius: 8, color: "#e2e8f0", fontSize: 14, boxSizing: "border-box", resize: "vertical" }}
      />

      <button
        onClick={analyse}
        disabled={loading || !text.trim()}
        style={{ marginTop: 12, padding: "10px 24px", background: "#6366f1", color: "#fff", border: "none", borderRadius: 8, fontWeight: 700, cursor: "pointer" }}
      >
        {loading ? "Analysing…" : "Analyse"}
      </button>

      {result && (
        <div style={{ marginTop: 24, padding: 20, background: "#1e2130", border: `1px solid ${colour}55`, borderRadius: 10 }}>
          <span style={{ color: colour, fontWeight: 700, fontSize: 20, textTransform: "capitalize" }}>
            {result.label}
          </span>
          <span style={{ color: "#64748b", marginLeft: 12, fontSize: 14 }}>
            {(result.score * 100).toFixed(1)}% confidence
          </span>
        </div>
      )}

      <div style={{ marginTop: 40, borderTop: "1px solid #2d3148", paddingTop: 24 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 12 }}>Headlines</h2>
        <button
          onClick={fetchHeadlines}
          style={{ padding: "10px 24px", background: "#0ea5e9", color: "#fff", border: "none", borderRadius: 8, fontWeight: 700, cursor: "pointer" }}
        >
          Load Headlines
        </button>

        {headlines.length > 0 && (
          <ul style={{ marginTop: 16, padding: 0, listStyle: "none" }}>
            {headlines.map((h, i) => (
              <li key={i} style={{
                padding: "10px 14px", marginBottom: 8,
                background: "#1e2130", border: "1px solid #2d3148",
                borderRadius: 8, fontSize: 13, color: "#cbd5e1"
              }}>
                {h}
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  )
}