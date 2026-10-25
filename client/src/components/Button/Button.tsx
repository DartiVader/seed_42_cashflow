import type { ButtonHTMLAttributes } from 'react';
import styles from './Button.module.css';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'dangerGhost'

type ButtonShape = 'pill' | 'square'

type ButtonSize = 'md' | 'sm'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    variant?: ButtonVariant
    shape?: ButtonShape
    size?: ButtonSize
}

const Button = ({ type = 'button', variant = 'primary', shape = 'pill', size = 'md', className, ...props }: ButtonProps) => {
    const classes = [styles.button, styles[variant], styles[shape], styles[size], className].filter(Boolean).join(' ')
    return <button type={type} className={classes} {...props} />;
};

export default Button;
