import { Link, NavLink, useLocation, useNavigate } from 'react-router';
import Button from '@/components/Button';
import { useAuth } from '@/context/AuthContext';
import styles from './Header.module.css';

const SECTIONS = [
    { to: '/forecast', label: 'Прогноз' },
    { to: '/dashboard', label: 'Данные' },
    { to: '/quality', label: 'Качество модели' },
]

const Header = () => {
    const { user, logout } = useAuth()
    const navigate = useNavigate()
    const { pathname } = useLocation()

    let homePath = '/'
    if (user) {
        homePath = pathname.startsWith('/forecast') ? pathname : '/forecast'
    }

    return (
        <header className={styles.header}>
            <div className={styles.inner}>
                <Link to={homePath} className={styles.logo}>
                    <img src="/icon.svg" alt="" className={styles.logoIcon} />
                    Seed 42
                </Link>
                {user && (
                    <nav className={styles.sections} aria-label="Разделы">
                        {SECTIONS.map((section) => (
                            <NavLink
                                key={section.to}
                                to={section.to}
                                className={({ isActive }) => (isActive ? `${styles.section} ${styles.active}` : styles.section)}
                            >
                                {section.label}
                            </NavLink>
                        ))}
                    </nav>
                )}
                <div className={styles.actions}>
                    {user
                        ? (
                            <>
                                <span className={styles.email}>{user.email}</span>
                                <Button variant="secondary" onClick={logout}>Выйти</Button>
                            </>
                        )
                        : (
                            <>
                                <Button variant="ghost" onClick={() => navigate('/demo')}>Демо</Button>
                                <Button variant="secondary" onClick={() => navigate('/auth')}>Вход / Регистрация</Button>
                            </>
                        )}
                </div>
            </div>
        </header>
    );
};

export default Header;
