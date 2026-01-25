import { useState, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "../hooks/authContext";
import LabeledInput from "../components/LabeledInput";
import Checkbox from "../components/Checkbox";

export default function LoginPage() {
    const { login, user, accessToken, loading } = useAuth();
    const navigate = useNavigate();

    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [rememberMe, setRememberMe] = useState(false);
    const [error, setError] = useState("");

    useEffect(() => {
        if (!loading && user && accessToken) {
            navigate("/", { replace: true });
        }
    }, [user, accessToken, loading, navigate]);

    async function handleLogin(e) {
        e.preventDefault();
        setError("");

        try {
            await login(email, password, rememberMe);
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
                Вход
            </h2>

            <form className="field-holder" onSubmit={handleLogin}>
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

                <Checkbox
                    label="Запомнить меня"
                    checked={rememberMe}
                    onChange={(e) => setRememberMe(e.target.checked)}
                    className="mt-2"
                />

                {error && (
                    <div style={{ color: "var(--color-error)", marginTop: 8 }}>
                        {error}
                    </div>
                )}

                <button className="button" style={{ marginTop: 16 }}>
                    Войти
                </button>
            </form>

            <p style={{ marginTop: 16 }}>
                Нет аккаунта? <Link to="/register">Зарегистрироваться</Link>
            </p>
        </div>
    );
}
