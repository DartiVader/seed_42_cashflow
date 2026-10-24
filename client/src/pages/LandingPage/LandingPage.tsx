import { useNavigate } from 'react-router';
import Button from '@/components/Button';
import ForecastLine from '@/components/ForecastLine';
import styles from './LandingPage.module.css';

const LandingPage = () => {
  const navigate = useNavigate()

  return (
    <main className={styles.page}>
      <div className={styles.inner}>
        <div className={styles.text}>
          <h1 className={styles.title}>Прогноз денег для вашего бизнеса</h1>
          <p className={styles.subtitle}>
            Загрузите банковскую выписку — покажем остаток на каждый день на месяц вперёд
            и заранее предупредим, если денег может не хватить
          </p>
          <Button className={styles.start} onClick={() => navigate('/auth')}>Начать</Button>
        </div>
        <div className={styles.illustration}>
          <ForecastLine />
        </div>
      </div>
    </main>
  )
}

export default LandingPage
