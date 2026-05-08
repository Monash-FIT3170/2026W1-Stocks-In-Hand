export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html>
      <body style={{ fontFamily: "system-ui", background: "#f8f9fb", color: "#191c1e", margin: 0 }}>
        {children}
      </body>
    </html>
  )
}
