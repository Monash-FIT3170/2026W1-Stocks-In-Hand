"use client"

import { useRouter } from "next/navigation"
import { useEffect, useMemo, useState } from "react"
import {
  fetchNotificationPreferences,
  resendAlertVerification,
  updateNotificationPreferences,
} from "../../lib/api"
import styles from "./page.module.css"

const SENTIMENT_OPTIONS = [
  { label: "Negative", value: "negative" },
  { label: "Neutral", value: "neutral" },
  { label: "Positive", value: "positive" },
]

const VERIFICATION_COPY = {
  unverified: {
    heading: "Email not verified",
    message: "Enable alerts to receive a confirmation link by email.",
    tone: "attention",
  },
  pending: {
    heading: "Verification pending",
    message: "Check your inbox and click the confirmation link we sent.",
    tone: "attention",
  },
  verified: {
    heading: "Email verified",
    message: "Your address can receive watchlist alerts.",
    tone: "success",
  },
  failed: {
    heading: "Verification failed",
    message: "We could not confirm this address. Request a new link and try again.",
    tone: "error",
  },
}

function draftFromPreferences(preferences) {
  return {
    enabled: Boolean(preferences.enabled),
    min_confidence: Number(preferences.min_confidence),
    sentiment_labels: Array.isArray(preferences.sentiment_labels)
      ? preferences.sentiment_labels
      : ["negative"],
  }
}

function sameDraft(preferences, draft) {
  if (!preferences || !draft) return true
  const savedLabels = [...preferences.sentiment_labels].sort().join(",")
  const draftLabels = [...draft.sentiment_labels].sort().join(",")
  return (
    Boolean(preferences.enabled) === draft.enabled &&
    Number(preferences.min_confidence) === draft.min_confidence &&
    savedLabels === draftLabels
  )
}

function formatDate(value) {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return new Intl.DateTimeFormat("en-AU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date)
}

export default function NotificationSettingsPage() {
  const router = useRouter()
  const [preferences, setPreferences] = useState(null)
  const [draft, setDraft] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [isResending, setIsResending] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  useEffect(() => {
    let cancelled = false

    async function loadPreferences() {
      setIsLoading(true)
      setError("")
      try {
        const result = await fetchNotificationPreferences()
        if (cancelled) return
        setPreferences(result)
        setDraft(draftFromPreferences(result))
      } catch (requestError) {
        if (cancelled) return
        if (requestError.status === 401) {
          router.replace("/sign-in?next=/settings/notifications")
          return
        }
        setError("Alert settings are unavailable right now. Check your connection and try again.")
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }

    loadPreferences()
    return () => {
      cancelled = true
    }
  }, [router])

  const isDirty = useMemo(
    () => !sameDraft(preferences, draft),
    [draft, preferences]
  )
  const verification = VERIFICATION_COPY[preferences?.verification_status] || VERIFICATION_COPY.unverified
  const deliveryFailed = ["failed", "rejected"].includes(preferences?.last_delivery_status)
  const lastDeliveryAt = formatDate(preferences?.last_delivery_at)
  const canResend = Boolean(
    preferences?.feature_enabled &&
    preferences?.enabled &&
    preferences.verification_status !== "verified"
  )

  function toggleSentiment(label) {
    setNotice("")
    setDraft((current) => {
      const selected = current.sentiment_labels.includes(label)
      if (selected && current.sentiment_labels.length === 1) return current
      return {
        ...current,
        sentiment_labels: selected
          ? current.sentiment_labels.filter((item) => item !== label)
          : [...current.sentiment_labels, label],
      }
    })
  }

  async function savePreferences(event) {
    event.preventDefault()
    if (!draft || !isDirty) return
    setIsSaving(true)
    setError("")
    setNotice("")
    try {
      const result = await updateNotificationPreferences(draft)
      setPreferences(result)
      setDraft(draftFromPreferences(result))
      setNotice(result.enabled ? "Alert preferences saved." : "Email alerts turned off.")
    } catch (requestError) {
      if (requestError.status === 401) {
        router.replace("/sign-in?next=/settings/notifications")
        return
      }
      setError(requestError.message || "Your alert preferences could not be saved.")
    } finally {
      setIsSaving(false)
    }
  }

  async function resendVerification() {
    setIsResending(true)
    setError("")
    setNotice("")
    try {
      const result = await resendAlertVerification()
      setPreferences(result)
      setDraft(draftFromPreferences(result))
      setNotice("A new verification email has been sent.")
    } catch (requestError) {
      if (requestError.status === 401) {
        router.replace("/sign-in?next=/settings/notifications")
        return
      }
      if (requestError.status === 429) {
        setError("A verification email was requested recently. Wait one minute and try again.")
      } else {
        setError(requestError.message || "A new verification email could not be requested.")
      }
    } finally {
      setIsResending(false)
    }
  }

  if (isLoading) {
    return (
      <section className={styles.page}>
        <div aria-live="polite" className={styles.loadingCard}>Loading alert settings</div>
      </section>
    )
  }

  if (!preferences || !draft) {
    return (
      <section className={styles.page}>
        <div className={styles.pageHeader}>
          <p className={styles.eyebrow}>Settings</p>
          <h1>Email alerts</h1>
        </div>
        <div className={styles.errorBanner} role="alert">
          <strong>Could not load alert settings</strong>
          <p>{error}</p>
          <button onClick={() => window.location.reload()} type="button">Try again</button>
        </div>
      </section>
    )
  }

  return (
    <section className={styles.page}>
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>Settings</p>
        <h1>Email alerts</h1>
        <p>Choose which watchlist sentiment updates should reach your inbox.</p>
      </header>

      {!preferences.feature_enabled && (
        <div className={styles.featureBanner} role="status">
          <strong>Email alerts are unavailable in this deployment.</strong>
          <span>You can still turn off alerts that were enabled earlier.</span>
        </div>
      )}

      {deliveryFailed && (
        <div className={styles.errorBanner} role="alert">
          <strong>The last email could not be delivered.</strong>
          <p>
            {preferences.last_delivery_error_code
              ? `The email service reported ${preferences.last_delivery_error_code}.`
              : "Check the verified address, then try again."}
            {lastDeliveryAt ? ` Last attempt: ${lastDeliveryAt}.` : ""}
          </p>
        </div>
      )}

      <div className={styles.settingsGrid}>
        <form className={styles.settingsCard} onSubmit={savePreferences}>
          <div className={styles.toggleRow}>
            <div>
              <h2>Watchlist alerts</h2>
              <p>Send an email when a saved company matches these rules.</p>
            </div>
            <label className={styles.switch}>
              <span className={styles.visuallyHidden}>Enable watchlist email alerts</span>
              <input
                checked={draft.enabled}
                disabled={!preferences.feature_enabled && !draft.enabled}
                onChange={(event) => {
                  setNotice("")
                  setDraft((current) => ({ ...current, enabled: event.target.checked }))
                }}
                role="switch"
                type="checkbox"
              />
              <span aria-hidden="true" className={styles.switchTrack} />
            </label>
          </div>

          <fieldset className={styles.ruleGroup} disabled={!draft.enabled || isSaving}>
            <legend>Confidence threshold</legend>
            <div className={styles.rangeHeader}>
              <span>Only send stronger signals</span>
              <output htmlFor="confidence-threshold">{Math.round(draft.min_confidence * 100)}%</output>
            </div>
            <input
              id="confidence-threshold"
              max="100"
              min="0"
              onChange={(event) => {
                setNotice("")
                setDraft((current) => ({
                  ...current,
                  min_confidence: Number(event.target.value) / 100,
                }))
              }}
              step="5"
              type="range"
              value={Math.round(draft.min_confidence * 100)}
            />
            <div aria-hidden="true" className={styles.rangeLabels}>
              <span>Any signal</span>
              <span>Highest confidence</span>
            </div>
          </fieldset>

          <fieldset className={styles.ruleGroup} disabled={!draft.enabled || isSaving}>
            <legend>Sentiment to include</legend>
            <p>Select at least one sentiment label.</p>
            <div className={styles.sentimentOptions}>
              {SENTIMENT_OPTIONS.map((option) => (
                <label className={styles.sentimentOption} key={option.value}>
                  <input
                    checked={draft.sentiment_labels.includes(option.value)}
                    onChange={() => toggleSentiment(option.value)}
                    type="checkbox"
                  />
                  <span className={styles.sentimentMarker} data-sentiment={option.value} />
                  <span>{option.label}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <div aria-atomic="true" aria-live="polite" className={styles.formMessage}>
            {error && <span className={styles.errorText}>{error}</span>}
            {!error && notice && <span className={styles.successText}>{notice}</span>}
          </div>

          <button
            className={styles.saveButton}
            disabled={
              !isDirty ||
              isSaving ||
              (draft.enabled && !preferences.feature_enabled)
            }
            type="submit"
          >
            {isSaving ? "Saving..." : "Save preferences"}
          </button>
        </form>

        <aside className={styles.statusCard}>
          <p className={styles.statusLabel}>Delivery address</p>
          <h2>{preferences.email}</h2>
          <div className={`${styles.verificationState} ${styles[verification.tone]}`}>
            <span aria-hidden="true" className={styles.statusDot} />
            <div>
              <strong>{verification.heading}</strong>
              <p>{verification.message}</p>
            </div>
          </div>
          {canResend && (
            <button
              className={styles.resendButton}
              disabled={isResending}
              onClick={resendVerification}
              type="button"
            >
              {isResending ? "Requesting..." : "Resend verification email"}
            </button>
          )}
          <dl className={styles.deliveryDetails}>
            <div>
              <dt>Alerts</dt>
              <dd>{preferences.enabled ? "On" : "Off"}</dd>
            </div>
            <div>
              <dt>Last delivery</dt>
              <dd>{preferences.last_delivery_status || "No delivery yet"}</dd>
            </div>
            {lastDeliveryAt && (
              <div>
                <dt>Last attempt</dt>
                <dd>{lastDeliveryAt}</dd>
              </div>
            )}
          </dl>
        </aside>
      </div>
    </section>
  )
}
