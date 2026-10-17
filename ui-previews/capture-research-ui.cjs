const path = require("path")
const { chromium } = require("C:\\Users\\aoswa\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\node_modules\\playwright")

const outputRoot = path.resolve(__dirname)
const issues = []

async function capture(browser, { name, url, viewport, reducedMotion = "no-preference", action }) {
  const context = await browser.newContext({
    colorScheme: "light",
    reducedMotion,
    viewport,
  })
  const page = await context.newPage()
  page.on("console", (message) => {
    if (message.type() === "error") issues.push(`${name} console: ${message.text()}`)
  })
  page.on("requestfailed", (request) => {
    issues.push(`${name} request: ${request.url()} ${request.failure()?.errorText || "failed"}`)
  })
  await page.goto(url, { waitUntil: "networkidle" })
  await page.locator("main").first().waitFor({ state: "visible" }).catch(() => {})
  if (action) await action(page)
  await page.waitForTimeout(800)
  await page.screenshot({ fullPage: true, path: path.join(outputRoot, `${name}.png`) })
  await context.close()
}

async function main() {
  const browser = await chromium.launch({ headless: true })
  await capture(browser, {
    name: "announcements-desktop",
    url: "http://127.0.0.1:3000/announcements/",
    viewport: { width: 1440, height: 1000 },
  })
  await capture(browser, {
    name: "announcements-mobile",
    url: "http://127.0.0.1:3000/announcements/",
    viewport: { width: 390, height: 844 },
  })
  await capture(browser, {
    name: "ticker-desktop",
    url: "http://127.0.0.1:3000/ticker/BHP/",
    viewport: { width: 1440, height: 1000 },
  })
  await capture(browser, {
    name: "ticker-mobile-reduced",
    url: "http://127.0.0.1:3000/ticker/BHP/",
    viewport: { width: 390, height: 844 },
    reducedMotion: "reduce",
  })
  await capture(browser, {
    name: "ticker-records-desktop",
    url: "http://127.0.0.1:3000/ticker/WDS/news/",
    viewport: { width: 1440, height: 1000 },
  })
  await capture(browser, {
    name: "ticker-deep-dive-mobile",
    url: "http://127.0.0.1:3000/ticker/WDS/deep-dive/",
    viewport: { width: 390, height: 844 },
  })
  await capture(browser, {
    name: "navigation-about-desktop",
    url: "http://127.0.0.1:3000/announcements/",
    viewport: { width: 1440, height: 1000 },
    action: (page) => page.getByRole("button", { name: /About/ }).click(),
  })
  await capture(browser, {
    name: "ticker-signals-desktop",
    url: "http://127.0.0.1:3000/ticker/WDS/",
    viewport: { width: 1440, height: 1000 },
  })
  await capture(browser, {
    name: "announcements-calendar-desktop",
    url: "http://127.0.0.1:3000/announcements/",
    viewport: { width: 1440, height: 1000 },
    action: (page) => page.locator("details summary").first().click(),
  })
  await capture(browser, {
    name: "search-results-desktop",
    url: "http://127.0.0.1:3000/search/",
    viewport: { width: 1440, height: 1000 },
  })
  await browser.close()
  console.log(`Captured 10 views; runtime issues: ${issues.length}`)
  for (const issue of issues) console.log(issue)
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
