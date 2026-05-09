// Minimal root layout for the prototype.
// Keep this file boring: document metadata/providers can be added here later, but
// page layout, navigation, footer, and visual tokens should remain in AppFrame and
// the CSS modules so individual feature work does not collide in the root layout.
export default function Layout({ children }) {
  return (
    <html>
      <body style={{ fontFamily: "system-ui", background: "#f8f9fb", color: "#191c1e", margin: 0 }}>
        {children}
      </body>
    </html>
  )
}
