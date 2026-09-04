"use client"

import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { Suspense, useCallback, useEffect, useRef, useState } from "react"
import { verifyAlertEmail } from "../lib/api"
import styles from "../unsubscribe/page.module.css"

function VerificationContent() {
  const searchParams = useSearchParams()
  const token = (searchParams.get("t") || searchParams.get("token") || "").trim()
  const requestedToken = useRef("")
  const [status, setStatus] = useState(token ? "working" : "missing")

  const submitVerification = useCallback(async () => {
    if (!token) {
      setStatus("missing")
      return
    }
    setStatus("working")
    try {
      await verifyAlertEmail(token)
      setStatus("complete")
    } catch (error) {
      setStatus(error?.status === 400 ? "invalid" : "error")
    }
  }, [token])

  useEffect(() => {
    if (!token || requestedToken.current === token) return
    requestedToken.current = token
    submitVerification()
  }, [submitVerification, token])

  return (
    <section className={styles.page}>
      <article aria-live="polite" className={styles.card}>
        <div aria-hidden="true" className={styles.mailIcon}><span /></div>

        {status === "working" && (
          <>
            <p className={styles.eyebrow}>Email alerts</p>
            <h1>Confirming your email</h1>
            <p>Please wait while we verify your alert subscription.</p>
            <span aria-label="Processing" className={styles.spinner} role="status" />
          </>
        )}

        {status === "complete" && (
          <>
            <p className={styles.eyebrow}>Email alerts</p>
            <h1>Email confirmed</h1>
            <p>Your address can now receive watchlist alerts.</p>
            <Link className={styles.primaryLink} href="/settings/notifications">Open alert settings</Link>
          </>
        )}

        {(status === "missing" || status === "invalid") && (
          <>
            <p className={styles.eyebrow}>Email alerts</p>
            <h1>This link is invalid</h1>
            <p>Open the newest verification email, or request another link from alert settings.</p>
            <Link className={styles.primaryLink} href="/settings/notifications">Open alert settings</Link>
          </>
        )}

        {status === "error" && (
          <>
            <p className={styles.eyebrow}>Email alerts</p>
            <h1>We could not verify your email</h1>
            <p>Check your connection and try the request again.</p>
            <button className={styles.primaryLink} onClick={submitVerification} type="button">Try again</button>
          </>
        )}
      </article>
    </section>
  )
}

export default function VerifyNotificationsPage() {
  return (
    <Suspense fallback={<section className={styles.page}><article className={styles.card}>Loading verification request</article></section>}>
      <VerificationContent />
    </Suspense>
  )
}
