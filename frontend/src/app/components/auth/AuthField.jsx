import styles from "../../page.module.css"
import { EyeIcon } from "../icons"

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
