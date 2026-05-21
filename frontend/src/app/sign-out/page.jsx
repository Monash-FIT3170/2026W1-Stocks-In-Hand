"use client"

import { useRouter } from "next/navigation"
import { useEffect } from "react"
import { apiFetch } from "../lib/api"

const AUTH_STORAGE_KEY = "stonks_signed_in"

export default function SignOutRoute() {
  const router = useRouter()

  useEffect(() => {
    async function signOut() {
      try {
        await apiFetch("/auth/sign-out", {
          method: "POST",
          credentials: "include",
        })
      } finally {
        window.localStorage.removeItem(AUTH_STORAGE_KEY)
        router.replace("/")
      }
    }

    signOut()
  }, [router])

  return null
}
