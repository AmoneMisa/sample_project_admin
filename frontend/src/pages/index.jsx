import {useCallback, useEffect, useRef, useState} from "react";
import EmojiPickerPopup from "../components/EmojiPicker";
import {useBeforeUnload, useLocation} from "react-router-dom";
import {useAuditLog} from "../hooks/useAuditLog";
import ConfirmDialog from "../components/ConfirmDialog";
import AddKeyBar from "../components/AddKeyBar";
import FiltersBar from "../components/FiltersBar";
import HistoryDialog from "../components/HistoryDialog";
import {useToast} from "../components/ToastContext";
import {FiClock, FiRotateCcw, FiSave, FiSmile, FiTrash} from "react-icons/fi";
import Checkbox from "../components/Checkbox";
import {useAuth} from "../hooks/authContext";
import CustomTable from "../components/CustomTable";

export default function Index() {
    const API_URL = process.env.REACT_APP_API_URL || "/api";

    const [languages, setLanguages] = useState([]);
    const [search, setSearch] = useState("");
    const [sortAsc, setSortAsc] = useState(true);
    const [editing, setEditing] = useState({key: null, lang: null, initial: ""});
    const [emojiPickerFor, setEmojiPickerFor] = useState(null);
    const [dirty, setDirty] = useState(false);
    const [ignoreBlur, setIgnoreBlur] = useState(false);
    const [filterStatus, setFilterStatus] = useState("all");
    const [filterErrorLevel, setFilterErrorLevel] = useState("all");
    const [deleteTarget, setDeleteTarget] = useState(null);
    const location = useLocation();
    const {accessToken, user} = useAuth();
    const canEdit = user && (user.role === "moderator" || user.role === "admin");

    useEffect(() => {
        const params = new URLSearchParams(location.search);
        const keyParam = params.get("key");
        if (keyParam) {
            setSearch(keyParam);
        }
    }, [location.search]);

    const editingInputRef = useRef(null);
    const {showToast} = useToast();

    const {
        translations,
        setTranslations,
        meta,
        setMeta,
        pushSnapshot,
        undo,
        canUndo,
        getHistory,
        markDeleted,
    } = useAuditLog();

    // LOAD DATA
    useEffect(() => {
        async function load() {
            if (!accessToken) return;
            const languagesRes = await fetch(`${API_URL}/languages/enabled`, {headers: {Authorization: `Bearer ${accessToken}`},});
            const langs = await languagesRes.json();
            if (!Array.isArray(langs)) {
                console.error("API вернул не массив:", langs);
                return;
            }
            setLanguages(langs);
            let all = {};
            for (const lang of langs) {
                const res = await fetch(`${API_URL}/translations?lang=${lang.code}`, {headers: {Authorization: `Bearer ${accessToken}`},});
                const data = await res.json();
                for (const [key, value] of Object.entries(data)) {
                    if (!all[key]) all[key] = {};
                    let v = value;
                    let isList = false;
                    if (typeof v === "string" && v.trim().startsWith("[") && v.trim().endsWith("]")) {
                        try {
                            const parsed = JSON.parse(v);
                            if (Array.isArray(parsed)) {
                                v = parsed.join("; ");
                                isList = true;
                            }
                        } catch {
                        }
                    }
                    all[key][lang.code] = v;
                    meta[key] = meta[key] || {};
                    if (isList) meta[key].isList = true;
                }
            }
            setTranslations(all);
        }

        load();
    }, [accessToken, setTranslations, meta]);
    const saveAll = useCallback(async () => {
        if (!accessToken) return;
        const items = [];
        for (const [key, values] of Object.entries(translations)) {
            const metaForKey = meta[key] || {};
            for (const lang of languages) {
                const rawValue = values[lang.code];
                const isList = !!metaForKey.isList;
                const payloadValue = isList ? String(rawValue).split(";").map((s) => s.trim()).filter(Boolean) : rawValue;
                items.push({key, lang: lang.code, value: payloadValue});
            }
        }
        await fetch(`${API_URL}/translations/bulk-update`, {
            method: "PATCH",
            headers: {"Content-Type": "application/json", Authorization: `Bearer ${accessToken}`,},
            body: JSON.stringify({items}),
        });
        showToast("Ключи успешно сохранены");
        setDirty(false);
    }, [translations, languages, meta, showToast, accessToken]);

    // CTRL+S
    useEffect(() => {
        function handleKey(e) {
            if (e.ctrlKey && e.key === "s") {
                e.preventDefault();
                saveAll();
                showToast("Ключи успешно сохранены");
            }
            if (e.ctrlKey && e.key === "z") {
                e.preventDefault();
                const metaSnapshot = undo();
                if (metaSnapshot) setMeta(metaSnapshot);
            }
        }

        window.addEventListener("keydown", handleKey);
        return () => window.removeEventListener("keydown", handleKey);
    }, [saveAll, undo, setMeta, showToast]);

    // BEFORE UNLOAD (browser)
    useEffect(() => {
        function beforeUnload(e) {
            if (!dirty) return;
            e.preventDefault();
            e.returnValue = "";
        }

        window.addEventListener("beforeunload", beforeUnload);
        return () => window.removeEventListener("beforeunload", beforeUnload);
    }, [dirty]);

    // BEFORE UNLOAD (router)
    useBeforeUnload(
        dirty
            ? (e) => {
                e.preventDefault();
                e.returnValue = "У вас есть несохранённые изменения!";
            }
            : undefined
    );

    // SAVE SINGLE VALUE
    async function saveValue(key, lang, newValue) {
        if (!accessToken) return;

        setDirty(true);

        const prevTranslations = translations;
        const prevMeta = meta;
        const nextTranslations = {
            ...prevTranslations,
            [key]: {
                ...prevTranslations[key],
                [lang]: newValue,
            },
        };

        const metaForKey = meta[key] || {};
        const isList = !!metaForKey.isList;

        const payloadValue = isList
            ? newValue.split(";").map(s => s.trim()).filter(Boolean)
            : newValue;

        pushSnapshot(
            nextTranslations,
            prevMeta,
            `Изменён ${lang} перевод у ключа '${key}'`
        );
        setTranslations(nextTranslations);
        setDirty(false);

        await fetch(`${API_URL}/translations/update`, {
            method: "PATCH",
            headers: {"Content-Type": "application/json", Authorization: `Bearer ${accessToken}`,},
            body: JSON.stringify({key, lang, value: payloadValue}),
        });
        showToast("Ключ сохранён");
    }

    // STATUS / ERROR LEVEL
    function getKeyStatus(key, values) {
        const langs = languages;
        if (!langs.length) return {errorLevel: "none", isComplete: false};

        const enabledCodes = langs.map((l) => l.code);
        const filled = enabledCodes.filter(
            (code) => typeof values[code] === "string" && values[code].trim() !== ""
        );

        const metaForKey = meta[key] || {};
        const allowEmpty = !!metaForKey.allowEmpty;

        if (allowEmpty) {
            return {
                errorLevel: "none",
                isComplete: !!metaForKey.isComplete,
            };
        }

        if (filled.length === 0) {
            return {errorLevel: "error", isComplete: false};
        }
        if (filled.length < enabledCodes.length) {
            return {errorLevel: "warning", isComplete: false};
        }
        return {errorLevel: "none", isComplete: true};
    }

    // FILTER + SORT
    const filtered = Object.entries(translations).filter(([key, valuesRaw]) => {
        const values = (typeof valuesRaw === "object" && valuesRaw !== null)
            ? valuesRaw
            : {};

        const s = search.toLowerCase();
        if (s && !key.toLowerCase().includes(s)) {
            const match = Object.values(values).some((v) =>
                String(v).toLowerCase().includes(s)
            );
            if (!match) return false;
        }

        const {errorLevel, isComplete} = getKeyStatus(key, values);

        if (filterStatus === "complete" && !isComplete) return false;
        if (filterStatus === "incomplete" && isComplete) return false;

        if (filterErrorLevel === "error" && errorLevel !== "error") return false;
        if (filterErrorLevel === "warning" && errorLevel !== "warning") return false;

        return true;
    });

    const sorted = [...filtered].sort(([a], [b]) =>
        sortAsc ? a.localeCompare(b) : b.localeCompare(a)
    );

    // ADD KEY
    function handleAddKey(newKey) {
        const prevTranslations = translations;
        const prevMeta = meta;

        if (prevTranslations[newKey]) return;

        const emptyRow = {};
        for (const lang of languages) {
            emptyRow[lang.code] = "";
        }

        const nextTranslations = {
            ...prevTranslations,
            [newKey]: emptyRow,
        };

        const nextMeta = {
            ...prevMeta,
            [newKey]: {allowEmpty: false},
        };

        pushSnapshot(
            nextTranslations,
            prevMeta,
            `Добавлен ключ '${newKey}'`
        );
        setTranslations(nextTranslations);
        setMeta(nextMeta);
        setDirty(true);
        setSearch(newKey);
    }

    // DELETE KEY
    function requestDeleteKey(key) {
        setDeleteTarget(key);
    }

    async function confirmDeleteKey() {
        if (!accessToken) return;
        const key = deleteTarget;
        if (!key) return;

        const prevTranslations = translations;
        const prevMeta = meta;

        const {[key]: removedTranslations, ...rest} = prevTranslations;
        const {[key]: removedMeta, ...restMeta} = prevMeta;

        markDeleted(key, removedTranslations, removedMeta);
        pushSnapshot(rest, restMeta, `Удалён ключ '${key}'`);
        setTranslations(rest);
        setMeta(restMeta);
        setDeleteTarget(null);
        await fetch(`${API_URL}/translations/delete`, {
            method: "DELETE",
            headers: {"Content-Type": "application/json", Authorization: `Bearer ${accessToken}`,},
            body: JSON.stringify({key}),
        });
        showToast("Ключ успешно удалён");
    }

    function cancelDeleteKey() {
        setDeleteTarget(null);
    }

    // TOGGLE META
    function toggleMetaFlag(key, flag) {
        setMeta((prev) => {
            const prevForKey = prev[key] || {};
            const nextForKey = {
                ...prevForKey,
                [flag]: !prevForKey[flag],
            };
            return {
                ...prev,
                [key]: nextForKey,
            };
        });
        setDirty(true);
    }

    function isKeyFullyEmpty(values, languages) {
        return languages.every((lang) => {
            const v = values[lang.code];

            if (typeof v !== "string") return true;

            return v.trim() === "";
        });
    }

    const [historyOpen, setHistoryOpen] = useState(false);

    function restoreSpecific(index) {
        const history = getHistory();
        const item = history[index];
        if (!item) return;

        setTranslations(structuredClone(item.state));

        setMeta(() => {
            const next = structuredClone(item.meta);
            for (const key of Object.keys(item.state)) {
                if (!next[key]) next[key] = {};
            }
            return next;
        });
    }

    // RENDER
    return (
        <div className={'page'} style={{padding: 24, fontFamily: "sans-serif"}}>
            <div className="page__header">
                <h1>Переводы</h1>
                <div style={{display: "flex", gap: 12}}>
                    {canEdit && (
                        <>
                            <button
                                className="button button_icon button_border"
                                style={{color: "var(--color-error)"}}
                                disabled={!canUndo}
                                onClick={() => {
                                    const metaSnapshot = undo();
                                    if (metaSnapshot) setMeta(metaSnapshot);
                                }}
                            >
                                <FiRotateCcw size={16}/>
                            </button>
                            <button
                                className="button button_icon button_border"
                                onClick={saveAll}
                                style={{color: "var(--color-accept)"}}
                            >
                                <FiSave size={16}/> Сохранить
                            </button>
                            <button
                                className="button button_icon button_border"
                                onClick={() => setHistoryOpen(true)}
                            >
                                <FiClock size={16}/> Изменения
                            </button>

                            <HistoryDialog
                                open={historyOpen}
                                history={getHistory()}
                                onRestore={restoreSpecific}
                                onClose={() => setHistoryOpen(false)}
                            />
                        </>
                    )}
                </div>

                <div className="page__header-row">
                    {canEdit && (
                        <AddKeyBar
                            onAdd={handleAddKey}
                            existingKeys={Object.keys(translations)}
                        />
                    )}

                    <FiltersBar
                        search={search}
                        setSearch={setSearch}
                        filterStatus={filterStatus}
                        setFilterStatus={setFilterStatus}
                        filterErrorLevel={filterErrorLevel}
                        setFilterErrorLevel={setFilterErrorLevel}
                    />
                </div>
            </div>

            <CustomTable
                columns={[
                    {
                        key: "key",
                        title: `Ключ ${sortAsc ? "▲" : "▼"}`,
                        render: (value) => (
                            {value}
                        ),
                    },
                    ...languages.map((lang) => ({
                        key: lang.code,
                        title: lang.code,
                        render: (_, row) => {
                            const raw = row.values[lang.code];
                            const val = Array.isArray(raw) ? raw.join("; ") : String(raw ?? "");
                            const isEditing = editing.key === row.key && editing.lang === lang.code;

                            return (
                                <div>
                                    {canEdit && isEditing ? (
                                        <div style={{position: "relative"}}>
                    <textarea
                        ref={editingInputRef}
                        autoFocus
                        defaultValue={val}
                        onBlur={(e) => {
                            if (ignoreBlur) {
                                setIgnoreBlur(false);
                                return;
                            }
                            const newValue = e.target.value;
                            if (newValue !== editing.initial) {
                                saveValue(row.key, lang.code, newValue);
                            }
                            setEditing({key: null, lang: null, initial: ""});
                        }}
                        onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                                e.preventDefault();
                                const newValue = e.target.value;
                                if (newValue !== editing.initial) {
                                    saveValue(row.key, lang.code, newValue);
                                }
                                setEditing({key: null, lang: null, initial: ""});
                            }
                        }}
                        className="input input_icons textarea"
                    />

                                            <div
                                                style={{
                                                    position: "absolute",
                                                    right: 8,
                                                    bottom: "-8px",
                                                    display: "flex",
                                                    gap: 2
                                                }}
                                            >
                                                <button
                                                    className="input-control"
                                                    onMouseDown={(e) => {
                                                        e.preventDefault();
                                                        setIgnoreBlur(true);
                                                    }}
                                                    onClick={() => {
                                                        const v = editingInputRef.current.value;
                                                        if (v !== editing.initial) {
                                                            saveValue(row.key, lang.code, v);
                                                        }
                                                        setEditing({key: null, lang: null, initial: ""});
                                                    }}
                                                >
                                                    <FiSave size={16}/>
                                                </button>

                                                <button
                                                    className="input-control"
                                                    onMouseDown={(e) => {
                                                        e.preventDefault();
                                                        setIgnoreBlur(true);
                                                    }}
                                                    onClick={() =>
                                                        setEmojiPickerFor({key: row.key, lang: lang.code})
                                                    }
                                                >
                                                    <FiSmile size={16}/>
                                                </button>
                                            </div>

                                            {emojiPickerFor &&
                                                emojiPickerFor.key === row.key &&
                                                emojiPickerFor.lang === lang.code && (
                                                    <EmojiPickerPopup
                                                        onSelect={(emoji) => {
                                                            const input = editingInputRef.current;
                                                            if (input) {
                                                                const start = input.selectionStart || 0;
                                                                const end = input.selectionEnd || 0;
                                                                const v = input.value || "";
                                                                input.value =
                                                                    v.slice(0, start) +
                                                                    emoji +
                                                                    v.slice(end);
                                                                input.dispatchEvent(
                                                                    new Event("input", {bubbles: true})
                                                                );
                                                            }
                                                            setEmojiPickerFor(null);
                                                        }}
                                                    />
                                                )}
                                        </div>
                                    ) : (
                                        val
                                    )}
                                </div>
                            );
                        },
                    })),
                    {
                        key: "meta",
                        title: "Флаги",
                        render: (_, row) => {
                            const metaForKey = meta[row.key] || {};
                            return canEdit ? (
                                <div style={{display: "flex", flexDirection: "column", gap: 4}}>
                                    {isKeyFullyEmpty(row.values, languages) && (
                                        <Checkbox
                                            label="Пустой перевод"
                                            checked={metaForKey.allowEmpty || false}
                                            onChange={() => toggleMetaFlag(row.key, "allowEmpty")}
                                        />
                                    )}
                                    <Checkbox
                                        label="Список"
                                        checked={metaForKey.isList || false}
                                        onChange={() => toggleMetaFlag(row.key, "isList")}
                                    />
                                </div>
                            ) : null;
                        },
                    },
                    {
                        key: "actions",
                        title: "Действия",
                        render: (_, row) =>
                            canEdit && (
                                <button
                                    className="button button_icon button_reject"
                                    onClick={() => requestDeleteKey(row.key)}
                                >
                                    <FiTrash size={16}/>
                                </button>
                            ),
                    },
                ]}
                data={sorted.map(([key, values]) => ({key, values}))}
            />

            {canEdit && (
                <ConfirmDialog
                    open={!!deleteTarget}
                    title="Удалить ключ?"
                    text={`Вы уверены, что хотите удалить ключ "${deleteTarget}"?`}
                    onConfirm={confirmDeleteKey}
                    onCancel={cancelDeleteKey}
                />
            )}
        </div>
    );
}
