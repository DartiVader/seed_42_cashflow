import { Link, useLocation, useNavigate } from 'react-router';
import Button from '@/components/Button';
import { useAuth } from '@/context/AuthContext';
import styles from './Header.module.css';

const Header = () => {
    const { user, logout } = useAuth()
    const navigate = useNavigate()
    const { pathname } = useLocation()

    const homePath = pathname.startsWith('/dashboard') ? '/dashboard' : '/'

    return (
        <header className={styles.header}>
            <div className={styles.inner}>
                <Link to={homePath} className={styles.logo}>
                    <img src="/icon.svg" alt="" className={styles.logoIcon} />
                    Seed 42
                </Link>
                <nav className={styles.actions}>
                    {user
                        ? (
                            <>
                                <Button variant="secondary" onClick={() => navigate('/dashboard')}>Профиль</Button>
                                <Button onClick={logout}>Выйти</Button>
                            </>
                        )
                        : <Button variant="secondary" onClick={() => navigate('/auth')}>Вход / Регистрация</Button>}
                </nav>
            </div>
        </header>
    );
};

export default Header;
