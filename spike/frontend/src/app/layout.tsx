export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html>
      <body style={{ fontFamily: "system-ui", background: "#0f1117", color: "#e2e8f0", margin: 0 }}>
        {children}
      </body>
    </html>
  )
}
