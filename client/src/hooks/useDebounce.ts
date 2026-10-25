import { useEffect, useState } from 'react';

export const useDebounce = <T>(value: T, delayMs: number): T => {
  const [debouncedValue, setDebouncedValue] = useState(value)

  useEffect(() => {
    const timerId = setTimeout(() => setDebouncedValue(value), delayMs)
    return () => clearTimeout(timerId)
  }, [value, delayMs])

  return debouncedValue
}
