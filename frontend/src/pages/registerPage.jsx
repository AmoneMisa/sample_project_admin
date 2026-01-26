import { useState, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "../hooks/authContext";
import LabeledInput from "../components/LabeledInput";

export default function RegisterPage() {
    const API_URL = process.env.REACT_APP_API_URL || "/api";

    const { login, user, accessToken, loading } = useAuth();
    const navigate = useNavigate();

    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [fullName, setFullName] = useState("");
    const [error, setError] = useState("");

    useEffect(() => {
        if (!loading && user && accessToken) {
            navigate("/", { replace: true });
        }
    }, [user, accessToken, loading, navigate]);

    async function handleRegister(e) {
        e.preventDefault();
        setError("");

        try {
            const res = await fetch(`${API_URL}/auth/register`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, password, full_name: fullName }),
            });

            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Ошибка регистрации");

            await login(email, password, true);
            navigate("/");
        } catch (err) {
            setError(err.message);
        }
    }

    if (loading) {
        return <div>Загрузка...</div>;
    }

    return (
        <div style={{ maxWidth: 400, margin: "80px auto" }}>
            <h2 className="gradient-text" style={{ marginBottom: 24 }}>
                Регистрация
            </h2>

            <form className="field-holder" onSubmit={handleRegister}>
                <LabeledInput
                    label="Email"
                    value={email}
                    onChange={setEmail}
                />

                <LabeledInput
                    label="Пароль"
                    type="password"
                    value={password}
                    onChange={setPassword}
                />

                <LabeledInput
                    label="Полное имя"
                    value={fullName}
                    onChange={setFullName}
                />

                {error && (
                    <div style={{ color: "var(--color-error)", marginTop: 8 }}>
                        {error}
                    </div>
                )}

                <button className="button" style={{ marginTop: 16 }}>
                    Зарегистрироваться
                </button>
            </form>

            <p style={{ marginTop: 16 }}>
                Уже есть аккаунт? <Link to="/login">Войти</Link>
            </p>
        </div>
    );
}
