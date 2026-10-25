import { useNavigate } from 'react-router';
import SideNav, { type SideNavItem } from '@/components/SideNav';
import { pluralDays } from '@/utils/format';

export type SidebarTab = SideNavItem

interface ForecastSidebarProps {
  tabs: SidebarTab[]
  activeTab: string
  isGuest: boolean
  historyDays?: number
  modelVersion?: string
  canPrint: boolean
  onSelect: (value: string) => void
  onTour: () => void
}

const HELP_ITEMS = (canPrint: boolean): SideNavItem[] => [
  { value: 'tour', label: 'Как пользоваться', icon: 'compass' },
  { value: 'print', label: 'Печать отчёта', icon: 'printer', disabled: !canPrint },
]

const ForecastSidebar = ({
  tabs, activeTab, isGuest, historyDays, modelVersion, canPrint, onSelect, onTour,
}: ForecastSidebarProps) => {
  const navigate = useNavigate()

  const handleSelect = (value: string) => {
    if (value === 'tour') {
      onTour()
    } else if (value === 'print') {
      window.print()
    } else {
      onSelect(value)
    }
  }

  const card = isGuest
    ? {
      title: 'Это пример',
      text: 'Зарегистрируйтесь — и прогноз построится по выписке вашего бизнеса.',
      action: { label: 'Попробовать', onClick: () => navigate('/auth') },
    }
    : {
      title: 'Прогноз по выписке',
      text: `${historyDays ? `История операций — ${pluralDays(historyDays)}. ` : ''}`
        + 'Каждое число можно проверить: откуда оно и из какого источника.',
      meta: modelVersion ? `модель ${modelVersion}` : undefined,
    }

  return (
    <SideNav
      groups={[
        { caption: 'Прогноз', items: tabs, isTabs: true },
        { caption: 'Помощь', items: HELP_ITEMS(canPrint) },
      ]}
      activeValue={activeTab}
      card={card}
      onSelect={handleSelect}
    />
  )
}

export default ForecastSidebar
