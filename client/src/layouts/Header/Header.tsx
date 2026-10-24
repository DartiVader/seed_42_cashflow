import { Link, useLocation, useNavigate } from 'react-router';
import Button from '@/components/Button';
import { useAuth } from '@/context/AuthContext';
import './Header.css'

const Header = () => {
    const { user, logout } = useAuth()
    const navigate = useNavigate()
    const { pathname } = useLocation()

    const homePath = pathname.startsWith('/dashboard') ? '/dashboard' : '/'

    return (
        <header>
            <Link to={homePath}>Seed 42</Link>
            {user
                ? (
                    <>
                        <Button onClick={() => navigate('/dashboard')}>Профиль</Button>
                        <Button onClick={logout}>Выйти</Button>
                    </>
                )
                : <Button onClick={() => navigate('/auth')}>Вход / Регистрация</Button>}
        </header>
    );
};

export default Header;
