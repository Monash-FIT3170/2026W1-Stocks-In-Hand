import styles from "../../page.module.css"
import { EmergingThemes } from "./EmergingThemes"
import { KeyNumbers } from "./KeyNumbers"
import { MarketIntelligence } from "./MarketIntelligence"

// Shared right-hand sidebar across all ticker brief tabs.
// Summary, News, and Deep Dive should all keep using this component so key numbers,
// market intelligence, and themes stay visually consistent across the brief experience.
export function BriefAside() {
  return <aside className={styles.briefAside}><KeyNumbers /><MarketIntelligence /><EmergingThemes /></aside>
}
