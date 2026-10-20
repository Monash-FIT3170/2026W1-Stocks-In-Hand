import Link from "next/link"
import { isContentTopic, recordTopics, topicFilterHref, topicLabel } from "../../lib/contentTopics"
import styles from "./TopicChips.module.css"

// A record's content topics. Known topics link to the market feed filtered by
// that topic; with linked={false} they are plain labels, for use inside a link
// or button.
export function TopicChips({ item, topics, linked = true, label = "Topics" }) {
  const values = recordTopics(topics ? { topics } : item)
  if (!values.length) return null
  return <ul className={styles.topics} aria-label={label}>
    {values.map((topic) => <li key={topic}>
      {linked && isContentTopic(topic)
        ? <Link className={styles.topic} href={topicFilterHref(topic)} title={`Show updates about ${topicLabel(topic).toLowerCase()}`}>{topicLabel(topic, { short: true })}</Link>
        : <span className={styles.topic}>{topicLabel(topic, { short: true })}</span>}
    </li>)}
  </ul>
}
