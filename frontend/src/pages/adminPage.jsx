import {useState, useEffect} from "react";
import {useAuth} from "../hooks/authContext";
import {useToast} from "../components/ToastContext";
import CustomTable from "../components/CustomTable";
import Checkbox from "../components/Checkbox";
import LabeledFileInput from "../components/LabeledFileInput";
import LabeledInput from "../components/LabeledInput";

// ISO 639-1 словарь
const ISO_LANGUAGES = {
    en: "English",
    ru: "Russian",
    kk: "Kazakh",
    fr: "French",
    de: "German",
    es: "Spanish",
    it: "Italian",
    zh: "Chinese",
    ja: "Japanese",
    uk: "Ukrainian",
    pl: "Polish",
    pt: "Portuguese",
    ar: "Arabic",
    tr: "Turkish",
    sv: "Swedish",
    fi: "Finnish",
    nl: "Dutch",
    cs: "Czech",
    bg: "Bulgarian",
    ro: "Romanian",
    hu: "Hungarian",
    el: "Greek",
    he: "Hebrew",
    hi: "Hindi",
    id: "Indonesian"
};

export default function AdminPage() {
    const API_URL = process.env.REACT_APP_API_URL || "/api";

    const {user, accessToken} = useAuth();
    const {showToast} = useToast();

    const [languages, setLanguages] = useState([]);
    const [newCode, setNewCode] = useState("");
    const [newName, setNewName] = useState("");
    const [suggestions, setSuggestions] = useState([]);

    async function loadLanguages() {
        const res = await fetch(`${API_URL}/languages`, {
            headers: {Authorization: `Bearer ${accessToken}`},
        });
        if (res.ok) {
            setLanguages(await res.json());
        }
    }

    useEffect(() => {
        if (accessToken) loadLanguages();
    }, [accessToken]);

    useEffect(() => {
        const code = newCode.trim().toLowerCase();
        if (!code) {
            setNewName("");
            setSuggestions([]);
            return;
        }

        if (ISO_LANGUAGES[code]) {
            setNewName(ISO_LANGUAGES[code]);
            setSuggestions([]);
        } else {
            const candidates = Object.keys(ISO_LANGUAGES)
                .filter(c =>
                    c.startsWith(code) ||
                    ISO_LANGUAGES[c].toLowerCase().includes(code)
                )
                .slice(0, 3);
            setSuggestions(candidates);
            setNewName("");
        }
    }, [newCode]);

    async function toggleLanguage(code, enabled) {
        await fetch(`${API_URL}/languages/${code}`, {
            method: "PATCH",
            headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${accessToken}`,
            },
            body: JSON.stringify({enabled}),
        });
        setLanguages(languages.map(l => l.code === code ? {...l, enabled} : l));
        showToast(`Язык ${code} ${enabled ? "включён" : "выключен"}`);
    }

    async function uploadFiles(files) {
        const formData = new FormData();
        for (const file of files) {
            formData.append("files", file);
        }
        const res = await fetch(`${API_URL}/translations/import`, {
            method: "POST",
            headers: {Authorization: `Bearer ${accessToken}`},
            body: formData,
        });
        if (res.ok) {
            showToast("Файлы успешно загружены");
        } else {
            showToast("Ошибка загрузки файлов");
        }
    }

    async function initLanguages() {
        const res = await fetch(`${API_URL}/languages/init`, {
            headers: {Authorization: `Bearer ${accessToken}`},
        });
        if (res.ok) {
            showToast("Языки инициализированы");
            loadLanguages();
        }
    }

    async function addLanguage() {
        if (!ISO_LANGUAGES[newCode]) {
            showToast("Некорректный код языка");
            return;
        }
        const res = await fetch(`${API_URL}/languages`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${accessToken}`,
            },
            body: JSON.stringify({code: newCode, name: newName, enabled: true}),
        });
        if (res.ok) {
            showToast("Язык добавлен");
            setNewCode("");
            setNewName("");
            loadLanguages();
        } else {
            showToast("Ошибка добавления языка");
        }
    }

    if (!user || !["admin", "moderator"].includes(user.role)) {
        return <div>Нет доступа</div>;
    }

    return (
        <div className="page" style={{padding: 24}}>
            <div className="page__header">
                <h1>Админка</h1>

                <h2>Загрузка переводов</h2>
                <LabeledFileInput
                    label="Загрузить файлы переводов"
                    multiple
                    accept="application/json"
                    onChange={uploadFiles}
                />

                {user.role === "admin" && languages.length === 0 && (
                    <button
                        className="button button_accept"
                        onClick={initLanguages}
                        style={{marginTop: 12, maxWidth: "300px"}}
                    >
                        Инициализировать языки
                    </button>
                )}
            </div>

            <h2>Языки</h2>
            <CustomTable
                columns={[
                    {key: "code", title: "Код"},
                    {key: "name", title: "Название"},
                    {
                        key: "enabled",
                        title: "Enabled",
                        render: (value, row) => (
                            <Checkbox
                                checked={value}
                                onChange={(e) => toggleLanguage(row.code, e.target.checked)}
                            />
                        ),
                    },
                ]}
                data={languages}
            />

            {user.role === "admin" && (
                <div style={{marginTop: 36}}>
                    <h3 style={{marginBottom: 20}}>Добавить язык</h3>
                    <div style={{display: "flex", gap: 12}}>
                        <LabeledInput
                            label="Код"
                            value={newCode}
                            onChange={setNewCode}
                            placeholder={"en"}
                        />
                        <LabeledInput
                            label="Название"
                            value={newName}
                            onChange={setNewName}
                            placeholder={"English"}
                        />
                    </div>

                    {suggestions.length > 0 && (
                        <div style={{marginTop: 8}}>
                            <span style={{fontSize: 14}}>Возможные варианты:</span>
                            <div style={{display: "flex", gap: 8, marginTop: 4}}>
                                {suggestions.map(code => (
                                    <button
                                        key={code}
                                        className="button button_border"
                                        onClick={() => {
                                            setNewCode(code);
                                            setNewName(ISO_LANGUAGES[code]);
                                            setSuggestions([]);
                                        }}
                                    >
                                        {code} — {ISO_LANGUAGES[code]}
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}

                    <button
                        className="button"
                        onClick={addLanguage}
                        style={{marginTop: 12}}
                    >
                        Добавить
                    </button>
                </div>
            )}
        </div>
    );
}
