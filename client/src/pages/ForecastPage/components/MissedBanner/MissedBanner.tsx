import Button from '@/components/Button';
import type { PlanFact } from '@/api/types';
import { shortDate } from '@/utils/format';
import { isProblem, missedText, planFactEventName } from '@/utils/planFactText';
import styles from './MissedBanner.module.css';

interface MissedBannerProps {
  data: PlanFact | null
  resolvedStreams: Set<string>
  onOpen: () => void
}

const MissedBanner = ({ data, resolvedStreams, onOpen }: MissedBannerProps) => {
  const missed = (data?.events ?? []).filter((event) => isProblem(event) && !resolvedStreams.has(event.stream_id ?? ''))
  if (missed.length === 0) {
    return null
  }
  const first = missed[0]

  return (
    <div className={styles.banner} role="alert">
      <span className={styles.icon} aria-hidden="true">!</span>
      <p className={styles.text}>
        <b>Ожидаемый платёж не прошёл:</b> {planFactEventName(first)}, ждали {shortDate(first.date)} — {missedText(first)}.
        {missed.length > 1 && ` И ещё ${missed.length - 1}.`} Прогноз уже пересчитан с учётом этого.
      </p>
      <Button size="sm" variant="secondary" onClick={onOpen}>Посмотреть план-факт</Button>
    </div>
  )
}

export default MissedBanner
