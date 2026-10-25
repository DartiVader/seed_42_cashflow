import Card from '@/components/Card';
import styles from './FileFormats.module.css';

const FORMATS = [
  {
    step: 1,
    title: 'Справочник компаний',
    file: 'companies.csv',
    columns: ['company_id', 'company_name', 'company_inn', 'legal_form', 'industry', '…'],
    text: 'Код, название, ИНН, форма (ООО или ИП) и вид деятельности.',
  },
  {
    step: 2,
    title: 'Банковские выписки',
    file: 'statements/C001.csv …',
    columns: ['company_id', 'operation_id', 'operation_date', 'amount', 'direction', '…', 'balance_eod'],
    text: 'Операции по счёту и остаток на конец дня — по нему сервис знает, сколько денег сейчас.',
  },
]

const FileFormats = () => (
  <Card title="Какие файлы подходят" subtitle="Разделитель — точка с запятой, кодировка UTF-8, первая строка — заголовки">
    <ol className={styles.list}>
      {FORMATS.map((format) => (
        <li key={format.step} className={styles.item}>
          <span className={styles.step}>{format.step}</span>
          <div className={styles.body}>
            <div className={styles.head}>
              <b>{format.title}</b>
              <code className={styles.file}>{format.file}</code>
            </div>
            <p className={styles.text}>{format.text}</p>
            <div className={styles.columns}>
              {format.columns.map((column) => <code key={column}>{column}</code>)}
            </div>
          </div>
        </li>
      ))}
    </ol>
    <p className={styles.note}>
      Можно выбрать сразу все файлы или один архив ZIP — справочник сервис загрузит первым сам.
      Повторно загруженные операции пропускаются, ведущие нули в ИНН сохраняются.
    </p>
  </Card>
)

export default FileFormats
