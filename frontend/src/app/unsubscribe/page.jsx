"use client"

import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { Suspense, useCallback, useEffect, useRef, useState } from "react"
import { unsubscribeAlerts } from "../lib/api"
import styles from "./page.module.css"

function UnsubscribeContent() {
  const searchParams = useSearchParams()
  const token = (
    searchParams.get("t") || searchParams.get("token") || ""
  ).trim()
  const requestedToken = useRef("")
  const [status, setStatus] = useState(token ? "working" : "missing")

  const submitUnsubscribe = useCallback(async () => {
    if (!token) {
      setStatus("missing")
      return
    }
    setStatus("working")
    try {
      await unsubscribeAlerts(token)
      setStatus("complete")
    } catch {
      setStatus("error")
    }
  }, [token])

  useEffect(() => {
    if (!token || requestedToken.current === token) return
    requestedToken.current = token
    submitUnsubscribe()
  }, [submitUnsubscribe, token])

  return (
    <section className={styles.page}>
      <article aria-live="polite" className={styles.card}>
        <div aria-hidden="true" className={styles.mailIcon}>
          <span />
        </div>

        {status === "working" && (
          <>
            <p className={styles.eyebrow}>Email alerts</p>
            <h1>Turning off alerts</h1>
            <p>Please wait while we update your subscription.</p>
            <span aria-label="Processing" className={styles.spinner} role="status" />
          </>
        )}

        {status === "complete" && (
          <>
            <p className={styles.eyebrow}>Email alerts</p>
            <h1>Request received</h1>
            <p>If this link matched a subscription, its email alerts are now turned off.</p>
            <Link className={styles.primaryLink} href="/">Return home</Link>
          </>
        )}

        {status === "missing" && (
          <>
            <p className={styles.eyebrow}>Email alerts</p>
            <h1>This link is incomplete</h1>
            <p>Open the full unsubscribe link from your email, or manage alerts after signing in.</p>
            <Link className={styles.primaryLink} href="/settings/notifications">Open alert settings</Link>
          </>
        )}

        {status === "error" && (
          <>
            <p className={styles.eyebrow}>Email alerts</p>
            <h1>We could not update alerts</h1>
            <p>Check your connection and try the request again.</p>
            <button className={styles.primaryLink} onClick={submitUnsubscribe} type="button">Try again</button>
          </>
        )}
      </article>
    </section>
  )
}

export default function UnsubscribePage() {
  return (
    <Suspense
      fallback={(
        <section className={styles.page}>
          <article className={styles.card}>Loading unsubscribe request</article>
        </section>
      )}
    >
      <UnsubscribeContent />
    </Suspense>
  )
}
