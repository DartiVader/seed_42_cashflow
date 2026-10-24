import type { ButtonHTMLAttributes } from 'react';
import './Button.css'

const Button = ({ type = 'button', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) => {
    return <button type={type} {...props} />;
};

export default Button;
