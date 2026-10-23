"use client"

import { useRouter } from "next/navigation"
import { useEffect, useMemo, useState } from "react"
import {
  changeCognitoPassword,
  getCognitoErrorMessage,
  hasCognitoSession,
  updateCognitoProfile,
} from "../../../auth/cognito"
import { AuthField } from "../../components/auth/AuthField"
import { friendlyAuthError } from "../../lib/authErrors"
import { changePassword, fetchCurrentInvestor, updateProfile } from "../../lib/api"
import styles from "./page.module.css"

function draftFromInvestor(investor) {
  return {
    username: investor.username || "",
    email: investor.email || "",
  }
}

function sameDraft(investor, draft) {
  if (!investor || !draft) return true
  return (investor.username || "") === draft.username && (investor.email || "") === draft.email
}

const EMPTY_PASSWORD_FORM = {
  current_password: "",
  new_password: "",
  confirm_password: "",
}

export default function ProfileSettingsPage() {
  const router = useRouter()
  const [investor, setInvestor] = useState(null)
  const [draft, setDraft] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isCognitoManaged, setIsCognitoManaged] = useState(false)
  const [loadError, setLoadError] = useState("")

  const [isSavingProfile, setIsSavingProfile] = useState(false)
  const [profileError, setProfileError] = useState("")
  const [profileNotice, setProfileNotice] = useState("")

  const [passwordForm, setPasswordForm] = useState(EMPTY_PASSWORD_FORM)
  const [isChangingPassword, setIsChangingPassword] = useState(false)
  const [passwordError, setPasswordError] = useState("")
  const [passwordNotice, setPasswordNotice] = useState("")

  useEffect(() => {
    let cancelled = false

    async function load() {
      setIsLoading(true)
      setLoadError("")
      try {
        const current = await fetchCurrentInvestor()
        if (cancelled) return
        if (!current) {
          router.replace("/sign-in?next=/settings/profile")
          return
        }
        const cognitoManaged = await hasCognitoSession()
        if (cancelled) return
        setInvestor(current)
        setDraft(draftFromInvestor(current))
        setIsCognitoManaged(cognitoManaged)
      } catch {
        if (cancelled) return
        setLoadError("Your profile is unavailable right now. Check your connection and try again.")
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [router])

  const isProfileDirty = useMemo(() => !sameDraft(investor, draft), [investor, draft])

  function updateDraftField(event) {
    setProfileNotice("")
    const { name, value } = event.target
    setDraft((current) => ({ ...current, [name]: value }))
  }

  function updatePasswordField(event) {
    setPasswordNotice("")
    const { name, value } = event.target
    setPasswordForm((current) => ({ ...current, [name]: value }))
  }

  async function saveProfile(event) {
    event.preventDefault()
    if (!draft || !isProfileDirty) return
    setIsSavingProfile(true)
    setProfileError("")
    setProfileNotice("")
    const emailChanged = draft.email !== investor.email
    const usernameChanged = draft.username !== (investor.username || "")

    try {
      if (isCognitoManaged) {
        const attributes = {}
        if (usernameChanged) attributes.name = draft.username
        if (emailChanged) attributes.email = draft.email
        await updateCognitoProfile(attributes)
        setInvestor((current) => ({ ...current, username: draft.username }))
        setProfileNotice(
          emailChanged
            ? "Profile updated. Check your new email address for a confirmation code."
            : "Profile updated successfully."
        )
      } else {
        const payload = {}
        if (usernameChanged) payload.username = draft.username
        if (emailChanged) payload.email = draft.email
        const result = await updateProfile(payload)
        setInvestor(result.investor)
        setDraft(draftFromInvestor(result.investor))
        setProfileNotice(result.message)
      }
    } catch (requestError) {
      if (requestError.status === 401) {
        router.replace("/sign-in?next=/settings/profile")
        return
      }
      setProfileError(
        isCognitoManaged
          ? getCognitoErrorMessage(requestError, requestError.message || "Your profile could not be updated.")
          : friendlyAuthError(requestError.message, "Your profile could not be updated.")
      )
    } finally {
      setIsSavingProfile(false)
    }
  }

  async function submitPasswordChange(event) {
    event.preventDefault()
    setPasswordError("")
    setPasswordNotice("")
    if (passwordForm.new_password !== passwordForm.confirm_password) {
      setPasswordError("New passwords do not match.")
      return
    }

    setIsChangingPassword(true)
    try {
      if (isCognitoManaged) {
        await changeCognitoPassword({
          oldPassword: passwordForm.current_password,
          newPassword: passwordForm.new_password,
        })
      } else {
        await changePassword({
          current_password: passwordForm.current_password,
          new_password: passwordForm.new_password,
        })
      }
      setPasswordForm(EMPTY_PASSWORD_FORM)
      setPasswordNotice("Your password has been changed.")
    } catch (requestError) {
      if (requestError.status === 401) {
        router.replace("/sign-in?next=/settings/profile")
        return
      }
      setPasswordError(
        isCognitoManaged
          ? getCognitoErrorMessage(requestError, requestError.message || "Your password could not be changed.")
          : friendlyAuthError(requestError.message, "Your password could not be changed.")
      )
    } finally {
      setIsChangingPassword(false)
    }
  }

  if (isLoading) {
    return (
      <section className={styles.page}>
        <div aria-live="polite" className={styles.loadingCard}>Loading profile</div>
      </section>
    )
  }

  if (!investor || !draft) {
    return (
      <section className={styles.page}>
        <div className={styles.pageHeader}>
          <p className={styles.eyebrow}>Settings</p>
          <h1>Profile</h1>
        </div>
        <div className={styles.errorBanner} role="alert">
          <strong>Could not load your profile</strong>
          <p>{loadError}</p>
          <button onClick={() => window.location.reload()} type="button">Try again</button>
        </div>
      </section>
    )
  }

  return (
    <section className={styles.page}>
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>Settings</p>
        <h1>Profile</h1>
        <p>Update your display name, email, and password.</p>
      </header>

      {investor.pending_email && (
        <div className={styles.featureBanner} role="status">
          <strong>Verification pending for {investor.pending_email}</strong>
          <span>Check that inbox and click the confirmation link to finish the change.</span>
        </div>
      )}

      {isCognitoManaged && (
        <div className={styles.featureBanner} role="status">
          <strong>This account is managed through Cognito.</strong>
          <span>Changing email requires confirming a code sent to the new address.</span>
        </div>
      )}

      <div className={styles.settingsStack}>
        <form className={styles.settingsCard} onSubmit={saveProfile}>
          <h2>Account details</h2>
          <AuthField
            autoComplete="name"
            label="Display name"
            name="username"
            onChange={updateDraftField}
            required
            value={draft.username}
          />
          <AuthField
            autoComplete="email"
            label="Email address"
            name="email"
            onChange={updateDraftField}
            required
            type="email"
            value={draft.email}
          />
          <div aria-atomic="true" aria-live="polite" className={styles.formMessage}>
            {profileError && <span className={styles.errorText}>{profileError}</span>}
            {!profileError && profileNotice && <span className={styles.successText}>{profileNotice}</span>}
          </div>
          <button className={styles.saveButton} disabled={!isProfileDirty || isSavingProfile} type="submit">
            {isSavingProfile ? "Saving..." : "Save profile"}
          </button>
        </form>

        <form className={styles.settingsCard} onSubmit={submitPasswordChange}>
          <h2>Change password</h2>
          <AuthField
            autoComplete="current-password"
            label="Current password"
            name="current_password"
            onChange={updatePasswordField}
            password
            required
            value={passwordForm.current_password}
          />
          <AuthField
            autoComplete="new-password"
            label="New password"
            minLength={8}
            name="new_password"
            onChange={updatePasswordField}
            password
            required
            value={passwordForm.new_password}
          />
          <AuthField
            autoComplete="new-password"
            label="Confirm new password"
            minLength={8}
            name="confirm_password"
            onChange={updatePasswordField}
            password
            required
            value={passwordForm.confirm_password}
          />
          <div aria-atomic="true" aria-live="polite" className={styles.formMessage}>
            {passwordError && <span className={styles.errorText}>{passwordError}</span>}
            {!passwordError && passwordNotice && <span className={styles.successText}>{passwordNotice}</span>}
          </div>
          <button className={styles.saveButton} disabled={isChangingPassword} type="submit">
            {isChangingPassword ? "Changing..." : "Change password"}
          </button>
        </form>
      </div>
    </section>
  )
}
