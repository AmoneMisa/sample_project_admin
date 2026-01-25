import {NavLink} from "react-router-dom";
import {FiHome, FiMenu, FiMessageSquare, FiUsers} from "react-icons/fi";
import {useAuth} from "../hooks/authContext";

export default function AdminMenu() {
    const {user} = useAuth();

    const isAdmin = user?.role === "admin";
    const isModerator = user?.role === "moderator";

    return (
        <nav className="admin-menu">
            <NavLink
                to="/"
                className={({ isActive }) =>
                    "admin-menu__item" + (isActive ? " admin-menu__item_active" : "")
                }
            >
                <FiHome size={18} />
                <span>Переводы</span>
            </NavLink>

            <NavLink
                to="/testimonials"
                className={({ isActive }) =>
                    "admin-menu__item" + (isActive ? " admin-menu__item_active" : "")
                }
            >
                <FiMessageSquare size={18} />
                <span>Отзывы</span>
            </NavLink>

            <NavLink
                to="/header-menu"
                className={({ isActive }) =>
                    "admin-menu__item" + (isActive ? " admin-menu__item_active" : "")
                }
            >
                <FiMenu size={18} />
                <span>Главное меню</span>
            </NavLink>

            {isAdmin && (
                <NavLink
                    to="/users"
                    className={({ isActive }) =>
                        "admin-menu__item" + (isActive ? " admin-menu__item_active" : "")
                    }
                >
                    <FiUsers size={18} />
                    <span>Пользователи</span>
                </NavLink>
            )}

            {(isAdmin || isModerator) && (
                <NavLink
                    to="/admin"
                    className={({ isActive }) =>
                        "admin-menu__item" + (isActive ? " admin-menu__item_active" : "")
                    }
                >
                    <FiMenu size={18} />
                    <span>Админка</span>
                </NavLink>
            )}
        </nav>
    );
}
