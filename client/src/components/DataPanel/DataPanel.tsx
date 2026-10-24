import { memo, useCallback, useState } from 'react';
import Button from '@/components/Button';
import CompaniesTable from '@/components/CompaniesTable';
import OperationsTable from '@/components/OperationsTable';
import { companiesApi } from '@/api/companies';
import { operationsApi } from '@/api/operations';
import { usePagedList } from '@/hooks/usePagedList';
import styles from './DataPanel.module.css';

type Tab = 'companies' | 'operations'

const DataPanel = ({ refreshKey }: { refreshKey: number }) => {
  const [tab, setTab] = useState<Tab>('companies')
  const [isEditing, setIsEditing] = useState(false)

  const companies = usePagedList(companiesApi.list, true, refreshKey)
  const operations = usePagedList(operationsApi.list, companies.isLoaded, refreshKey)

  const reloadCompanies = companies.reload
  const reloadOperations = operations.reload

  const handleCompaniesChanged = useCallback(() => {
    reloadCompanies()
    reloadOperations()
  }, [reloadCompanies, reloadOperations])

  return (
    <section>
      <div className={styles.toolbar}>
        <div className={styles.tabs}>
          <Button onClick={() => setTab('companies')} disabled={tab === 'companies'}>Компании</Button>
          <Button onClick={() => setTab('operations')} disabled={tab === 'operations'}>Операции</Button>
        </div>
        <Button onClick={() => setIsEditing((current) => !current)}>
          {isEditing ? 'Готово' : 'Редактировать'}
        </Button>
      </div>
      <div className={styles.window}>
        {tab === 'companies'
          ? (
            <CompaniesTable
              data={companies.data}
              page={companies.page}
              isLoading={companies.isLoading}
              errors={companies.errors}
              isEditing={isEditing}
              onPageChange={companies.setPage}
              onChanged={handleCompaniesChanged}
            />
          )
          : (
            <OperationsTable
              data={operations.data}
              page={operations.page}
              isLoading={operations.isLoading}
              errors={operations.errors}
              isEditing={isEditing}
              onPageChange={operations.setPage}
              onChanged={reloadOperations}
            />
          )}
      </div>
    </section>
  )
}

export default memo(DataPanel)
