const TOUR_KEY = 'seed42-tour-done'
const DEMO_TOUR_KEY = 'seed42-demo-tour-done'

const cushionKey = (companyId: string) => `seed42-cushion-${companyId}`

const getLocal = () => localStorage

const getSession = () => sessionStorage

const read = (key: string, getStorage: () => Storage = getLocal) => {
  try {
    return getStorage().getItem(key)
  } catch {
    return null
  }
}

const write = (key: string, value: string, getStorage: () => Storage = getLocal) => {
  try {
    getStorage().setItem(key, value)
  } catch {
    return
  }
}

export const preferenceStorage = {
  isTourDone: (demoOnly: boolean) => (demoOnly ? read(DEMO_TOUR_KEY, getSession) : read(TOUR_KEY)) !== null,

  markTourDone: (demoOnly: boolean) => (demoOnly ? write(DEMO_TOUR_KEY, '1', getSession) : write(TOUR_KEY, '1')),

  getCushion: (companyId: string) => {
    const saved = Number(read(cushionKey(companyId)) ?? 0)
    return Number.isFinite(saved) ? saved : 0
  },

  setCushion: (companyId: string, cushion: number) => write(cushionKey(companyId), String(cushion)),
}
