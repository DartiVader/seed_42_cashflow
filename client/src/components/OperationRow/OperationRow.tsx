import { memo } from 'react';
import type { Operation } from '@/api/types';
import { formatDate, formatMoney } from '@/utils/format';
import styles from './OperationRow.module.css';

const OperationRow = ({ operation }: { operation: Operation }) => {
  return (
    <tr>
      <td className={styles.nowrap}>{formatDate(operation.date)}</td>
      <td>{operation.companyId}</td>
      <td>{operation.operationId}</td>
      <td className={operation.direction === 'Поступление' ? `${styles.amount} ${styles.income}` : styles.amount}>
        {formatMoney(operation.amount, operation.direction)}
      </td>
      <td>{operation.counterpartyName}</td>
      <td>{operation.counterpartyInn ?? '—'}</td>
      <td>{operation.paymentPurpose ?? '—'}</td>
    </tr>
  )
}

export default memo(OperationRow)
