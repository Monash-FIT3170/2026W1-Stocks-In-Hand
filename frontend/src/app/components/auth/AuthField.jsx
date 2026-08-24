"use client"

import { useState } from "react"
import styles from "../../page.module.css"
import { EyeIcon } from "../icons"

// Shared auth input used by the sign-in and sign-up forms.
export function AuthField({
  label,
  name,
  placeholder,
  password = false,
  value,
  onChange,
  required = false,
  autoComplete,
  maxLength,
  minLength,
  type,
}) {
  const [isPasswordVisible, setIsPasswordVisible] = useState(false)
  const inputType = password ? (isPasswordVisible ? "text" : "password") : type || (name === "email" ? "email" : "text")

  return (
    <label className={styles.field}>
      <span>{label}</span>
      <div>
        <input
          autoComplete={autoComplete}
          maxLength={maxLength}
          minLength={minLength}
          name={name}
          onChange={onChange}
          placeholder={placeholder}
          required={required}
          type={inputType}
          value={value}
        />
        {password ? (
          <button
            aria-label={isPasswordVisible ? "Hide password" : "Show password"}
            className={styles.passwordToggle}
            onClick={() => setIsPasswordVisible((visible) => !visible)}
            type="button"
          >
            <EyeIcon />
          </button>
        ) : null}
      </div>
    </label>
  )
}
