import { createContext, useContext, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

const AuthContext = createContext(null);
const API_URL = process.env.REACT_APP_API_URL;

export function AuthProvider({ children }) {
    const navigate = useNavigate();

    const [user, setUser] = useState(null);
    const [accessToken, setAccessToken] = useState(null);
    const [refreshToken, setRefreshToken] = useState(null);
    const [loading, setLoading] = useState(true);

    // -----------------------------
    //  Загрузка токенов при старте
    // -----------------------------
    useEffect(() => {
        const storedAccess =
            localStorage.getItem("access_token") ||
            sessionStorage.getItem("access_token");

        const storedRefresh =
            localStorage.getItem("refresh_token") ||
            sessionStorage.getItem("refresh_token");

        if (storedAccess && storedRefresh) {
            setAccessToken(storedAccess);
            setRefreshToken(storedRefresh);
            fetchUser(storedAccess).finally(() => setLoading(false));
        } else {
            setLoading(false);
        }
    }, []);

    // -----------------------------
    //  Получение профиля
    // -----------------------------
    async function fetchUser(token) {
        try {
            const res = await fetch(`${API_URL}/auth/me`, {
                headers: { Authorization: `Bearer ${token}` },
            });

            if (!res.ok) throw new Error("Unauthorized");

            const data = await res.json();
            setUser(data);
        } catch {
            await handleRefresh();
        }
    }

    // -----------------------------
    //  Логин
    // -----------------------------
    async function login(email, password, remember) {
        const res = await fetch(`${API_URL}/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password, remember_me: remember }),
        });

        const data = await res.json();

        if (!res.ok) {
            throw new Error(data.detail || "Ошибка входа");
        }

        // сохраняем токены
        if (remember) {
            localStorage.setItem("access_token", data.access_token);
            localStorage.setItem("refresh_token", data.refresh_token);
        } else {
            sessionStorage.setItem("access_token", data.access_token);
            sessionStorage.setItem("refresh_token", data.refresh_token);
        }

        setAccessToken(data.access_token);
        setRefreshToken(data.refresh_token);
        setUser({
            id: data.id,
            email: data.email,
            full_name: data.full_name,
            role: data.role,
            permissions: data.permissions,
        }); // <--- сразу берём из ответа

        navigate("/");
    }

    // -----------------------------
    //  Logout
    // -----------------------------
    async function logout() {
        try {
            await fetch(`${API_URL}/auth/logout`, {
                method: "POST",
                headers: { Authorization: `Bearer ${accessToken}` },
            });
        } catch {}

        localStorage.clear();
        sessionStorage.clear();

        setAccessToken(null);
        setRefreshToken(null);
        setUser(null);

        navigate("/login");
    }

    // -----------------------------
    //  Refresh token
    // -----------------------------
    async function handleRefresh() {
        if (!refreshToken) return logout();

        const res = await fetch(`${API_URL}/auth/refresh`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: refreshToken }),
        });

        const data = await res.json();

        if (!res.ok) {
            return logout();
        }

        // сохраняем только туда, где refresh лежит
        if (localStorage.getItem("refresh_token")) {
            localStorage.setItem("access_token", data.access_token);
        } else {
            sessionStorage.setItem("access_token", data.access_token);
        }

        setAccessToken(data.access_token);

        await fetchUser(data.access_token);

        return data.access_token;
    }

    // -----------------------------
    //  Авто‑refresh каждые 10 минут
    // -----------------------------
    useEffect(() => {
        if (!refreshToken) return;

        const interval = setInterval(() => {
            handleRefresh();
        }, 10 * 60 * 1000);

        return () => clearInterval(interval);
    }, [refreshToken]);

    return (
        <AuthContext.Provider
            value={{
                user,
                accessToken,
                login,
                logout,
                refresh: handleRefresh,
                loading
            }}
        >
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    return useContext(AuthContext);
}
