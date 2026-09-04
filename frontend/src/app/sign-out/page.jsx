"use client"

import { useRouter } from "next/navigation"
import { useEffect } from "react"
import { apiFetch } from "../lib/api"
import { isCognitoAuthEnabled, signOutFromCognito } from "../../auth/cognito"

const AUTH_STORAGE_KEY = "stonks_signed_in"

export default function SignOutRoute() {
  const router = useRouter()

  useEffect(() => {
    async function signOut() {
      try {
        if (isCognitoAuthEnabled()) {
          await signOutFromCognito()
        } else {
          await apiFetch("/auth/sign-out", {
            method: "POST",
            credentials: "include",
          })
        }
      } finally {
        window.localStorage.removeItem(AUTH_STORAGE_KEY)
        window.dispatchEvent(new Event("stonks-auth-changed"))
        router.replace("/")
      }
    }

    signOut()
  }, [router])

  return null
}
