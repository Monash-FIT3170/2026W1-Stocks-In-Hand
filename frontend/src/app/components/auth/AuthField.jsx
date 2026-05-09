import styles from "../../page.module.css"
import { EyeIcon } from "../icons"

// Visual-only field component for the auth prototype screens.
// This deliberately avoids validation, controlled form state, and password reveal
// behavior. Add those pieces only when the auth implementation is being connected.
export function AuthField({
  label,
  placeholder,
  password = false,
}) {
  return (
    <label className={styles.field}>
      <span>{label}</span>
      <div>
        <input placeholder={placeholder} type={password ? "password" : "text"} />
        {password && <EyeIcon />}
      </div>
    </label>
  )
}
