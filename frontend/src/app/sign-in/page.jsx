"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { AuthField } from "../components/auth/AuthField"
import { apiFetch } from "../lib/api"
import { friendlyAuthError } from "../lib/authErrors"
import styles from "../page.module.css"

const AUTH_STORAGE_KEY = "stonks_signed_in"

function getErrorMessage(data, fallback) {
  if (Array.isArray(data.detail)) {
    return data.detail.map((error) => error.msg).join(", ")
  }

  if (typeof data.detail === "string") {
    return data.detail
  }

  return fallback
}

export default function SignInRoute() {
  const router = useRouter()
  const [form, setForm] = useState({ email: "", password: "" })
  const [error, setError] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)

  function updateForm(event) {
    setForm((current) => ({
      ...current,
      [event.target.name]: event.target.value,
    }))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError("")
    setIsSubmitting(true)

    try {
      const response = await apiFetch("/auth/sign-in", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      })
      const data = await response.json().catch(() => ({}))

      if (!response.ok) {
        throw new Error(friendlyAuthError(getErrorMessage(data, "Could not sign in"), "Could not sign in"))
      }

      window.localStorage.setItem(AUTH_STORAGE_KEY, "true")
      window.dispatchEvent(new Event("stonks-auth-changed"))
      router.push("/watchlist")
    } catch (err) {
      setError(
        err instanceof TypeError
          ? "Could not reach the sign-in service. Check your connection and try again."
          : friendlyAuthError(err.message, "Could not sign in")
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <section className={styles.authPage}>
        <form className={styles.authCard} onSubmit={handleSubmit}>
          <h1>Welcome back</h1>
          <p>Access your saved ASX watchlist and company research.</p>
          <AuthField
            autoComplete="email"
            label="Email address"
            maxLength={320}
            name="email"
            onChange={updateForm}
            placeholder="name@example.com"
            required
            value={form.email}
          />
          <AuthField
            autoComplete="current-password"
            label="Password"
            minLength={1}
            name="password"
            onChange={updateForm}
            placeholder="Enter your password"
            password
            required
            value={form.password}
          />
          {error ? <p aria-live="assertive" className={styles.authError} role="alert">{error}</p> : null}
          <button className={styles.authSubmit} disabled={isSubmitting} type="submit">
            {isSubmitting ? "Signing in…" : "Sign In"}
          </button>
          <span className={styles.authSwap}>Don&apos;t have an account?<Link href="/sign-up">Sign up</Link></span>
        </form>
    </section>
  )
}
