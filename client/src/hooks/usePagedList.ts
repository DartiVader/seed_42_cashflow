import { useCallback, useEffect, useState } from 'react';
import { getErrorMessages } from '@/api/api';
import type { Page } from '@/api/types';

const PAGE_SIZE = 50

export interface PagedList<T> {
  data: Page<T> | null
  page: number
  isLoading: boolean
  isLoaded: boolean
  errors: string[]
  setPage: (page: number) => void
  reload: () => void
}

export const usePagedList = <T>(
  load: (page: number, size: number) => Promise<Page<T>>,
  isEnabled: boolean,
  refreshKey: number,
): PagedList<T> => {
  const [data, setData] = useState<Page<T> | null>(null)
  const [page, setPage] = useState(0)
  const [errors, setErrors] = useState<string[]>([])
  const [version, setVersion] = useState(0)
  const [finishedRequestKey, setFinishedRequestKey] = useState<string | null>(null)

  const requestKey = `${page}:${refreshKey}:${version}`

  useEffect(() => {
    if (!isEnabled) {
      return
    }
    let isActual = true
    load(page, PAGE_SIZE)
      .then((result) => {
        if (!isActual) {
          return
        }
        if (result.items.length === 0 && page > 0) {
          setPage(Math.max(result.totalPages - 1, 0))
          return
        }
        setData(result)
        setErrors([])
      })
      .catch((error) => {
        if (isActual) {
          setErrors(getErrorMessages(error))
        }
      })
      .finally(() => {
        if (isActual) {
          setFinishedRequestKey(requestKey)
        }
      })
    return () => {
      isActual = false
    }
  }, [load, page, isEnabled, requestKey])

  const reload = useCallback(() => {
    setVersion((current) => current + 1)
  }, [])

  return {
    data,
    page,
    isLoading: isEnabled && finishedRequestKey !== requestKey,
    isLoaded: finishedRequestKey !== null,
    errors,
    setPage,
    reload,
  }
}
