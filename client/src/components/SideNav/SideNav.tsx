import type { ReactNode } from 'react';
import Button from '@/components/Button';
import CsvMascot from '@/components/CsvMascot';
import Icon, { type IconName } from '@/components/Icon';
import styles from './SideNav.module.css';

export interface SideNavItem {
  value: string
  label: string
  icon: IconName
  badge?: number
  isAlert?: boolean
  tour?: string
  disabled?: boolean
}

export interface SideNavGroup {
  caption: string
  items: SideNavItem[]
  /** вкладки (role="tab", выделение активной) или просто действия */
  isTabs?: boolean
}

export interface SideNavCard {
  title: string
  text: ReactNode
  meta?: string
  action?: { label: string, onClick: () => void }
}

interface SideNavProps {
  groups: SideNavGroup[]
  activeValue?: string
  card?: SideNavCard
  onSelect: (value: string) => void
}

/** Левая панель разделов: группы с подписью, пункты с иконками и счётчиками, карточка с маскотом внизу. */
const SideNav = ({ groups, activeValue, card, onSelect }: SideNavProps) => {
  return (
    <aside className={styles.sidebar}>
      {groups.map((group) => (
        <div key={group.caption} className={styles.group}>
          <span className={styles.caption}>{group.caption}</span>
          <nav
            className={styles.menu}
            role={group.isTabs ? 'tablist' : undefined}
            aria-orientation={group.isTabs ? 'vertical' : undefined}
          >
            {group.items.map((item) => (
              <button
                key={item.value}
                type="button"
                role={group.isTabs ? 'tab' : undefined}
                aria-selected={group.isTabs ? item.value === activeValue : undefined}
                className={styles.item}
                data-tour={item.tour}
                disabled={item.disabled}
                onClick={() => onSelect(item.value)}
              >
                <Icon name={item.icon} />
                <span className={styles.label}>{item.label}</span>
                {item.badge !== undefined && item.badge > 0 && (
                  <span className={styles.badge} data-alert={item.isAlert === true}>
                    {item.badge.toLocaleString('ru-RU')}
                  </span>
                )}
              </button>
            ))}
          </nav>
        </div>
      ))}

      {card && (
        <div className={styles.card}>
          <CsvMascot className={styles.mascot} />
          <b className={styles.cardTitle}>{card.title}</b>
          <p className={styles.cardText}>{card.text}</p>
          {card.meta && <span className={styles.cardMeta}>{card.meta}</span>}
          {card.action && (
            <Button size="sm" className={styles.cardButton} onClick={card.action.onClick}>{card.action.label}</Button>
          )}
        </div>
      )}
    </aside>
  )
}

export default SideNav
