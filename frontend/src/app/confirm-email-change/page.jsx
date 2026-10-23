"use client"

import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { Suspense, useCallback, useEffect, useRef, useState } from "react"
import { confirmEmailChange } from "../lib/api"
import styles from "../unsubscribe/page.module.css"

function ConfirmationContent() {
  const searchParams = useSearchParams()
  const token = (searchParams.get("token") || "").trim()
  const requestedToken = useRef("")
  const [status, setStatus] = useState(token ? "working" : "missing")

  const submitConfirmation = useCallback(async () => {
    if (!token) {
      setStatus("missing")
      return
    }
    setStatus("working")
    try {
      await confirmEmailChange(token)
      setStatus("complete")
    } catch (error) {
      setStatus(error?.status === 400 ? "invalid" : "error")
    }
  }, [token])

  useEffect(() => {
    if (!token || requestedToken.current === token) return
    requestedToken.current = token
    submitConfirmation()
  }, [submitConfirmation, token])

  return (
    <section className={styles.page}>
      <article aria-live="polite" className={styles.card}>
        <div aria-hidden="true" className={styles.mailIcon}><span /></div>

        {status === "working" && (
          <>
            <p className={styles.eyebrow}>Account email</p>
            <h1>Confirming your new email</h1>
            <p>Please wait while we confirm the address change.</p>
            <span aria-label="Processing" className={styles.spinner} role="status" />
          </>
        )}

        {status === "complete" && (
          <>
            <p className={styles.eyebrow}>Account email</p>
            <h1>Email address updated</h1>
            <p>You can now sign in with your new email address.</p>
            <Link className={styles.primaryLink} href="/settings/profile">Open profile settings</Link>
          </>
        )}

        {(status === "missing" || status === "invalid") && (
          <>
            <p className={styles.eyebrow}>Account email</p>
            <h1>This link is invalid or has expired</h1>
            <p>Open the newest confirmation email, or request the change again from profile settings.</p>
            <Link className={styles.primaryLink} href="/settings/profile">Open profile settings</Link>
          </>
        )}

        {status === "error" && (
          <>
            <p className={styles.eyebrow}>Account email</p>
            <h1>We could not confirm your email</h1>
            <p>Check your connection and try the request again.</p>
            <button className={styles.primaryLink} onClick={submitConfirmation} type="button">Try again</button>
          </>
        )}
      </article>
    </section>
  )
}

export default function ConfirmEmailChangePage() {
  return (
    <Suspense fallback={<section className={styles.page}><article className={styles.card}>Loading confirmation request</article></section>}>
      <ConfirmationContent />
    </Suspense>
  )
}
