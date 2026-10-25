import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import Card from '@/components/Card';
import type { QualityHorizon } from '@/api/types';
import { shortMoney } from '@/utils/format';
import styles from './HorizonErrors.module.css';

const COLORS = {
  mae: 'var(--color-primary)',
  rmse: 'var(--color-ink)',
  grid: 'var(--color-border)',
  axis: 'var(--color-text-muted)',
}

const squareMoney = (value: number) => `${(value / 1e9).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} млрд ₽²`

const HorizonErrors = ({ rows }: { rows: QualityHorizon[] }) => {
  const sorted = [...rows].sort((a, b) => a.horizon - b.horizon)
  const data = sorted.map((row) => ({ label: `${row.horizon} дн.`, mae: row.mae, rmse: row.rmse }))

  return (
    <Card
      title="Ошибка остатка по горизонтам"
      subtitle="На сколько рублей прогноз остатка в среднем расходится с фактом через 1, 7, 14 и 30 дней"
    >
      <div className={styles.layout}>
        <table className={styles.table}>
          <thead>
            <tr><th>Горизонт</th><th>MAE</th><th>RMSE</th><th>MSE</th></tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr key={row.horizon}>
                <td>{row.horizon} дн.</td>
                <td>{row.mae !== undefined ? shortMoney(row.mae) : '—'}</td>
                <td>{row.rmse !== undefined ? shortMoney(row.rmse) : '—'}</td>
                <td>{row.mse !== undefined ? squareMoney(row.mse) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className={styles.chart}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 12, fill: COLORS.axis }} tickLine={false} />
              <YAxis tickFormatter={(value: number) => shortMoney(value)} tick={{ fontSize: 12, fill: COLORS.axis }}
                tickLine={false} axisLine={false} width={80} />
              <Tooltip formatter={(value) => shortMoney(Number(value))} />
              <Legend />
              <Bar dataKey="mae" name="MAE — средняя ошибка" fill={COLORS.mae} radius={[4, 4, 0, 0]}
                isAnimationActive={false} />
              <Bar dataKey="rmse" name="RMSE — с учётом крупных промахов" fill={COLORS.rmse} radius={[4, 4, 0, 0]}
                isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </Card>
  )
}

export default HorizonErrors
