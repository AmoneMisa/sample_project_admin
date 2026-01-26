import {useEffect, useState} from "react";
import {FiEdit, FiRotateCcw, FiTrash} from "react-icons/fi";
import {useToast} from "../components/ToastContext";
import {useAuditLog} from "../hooks/useAuditLog";
import MenuItemDialog from "../components/MenuItemDialog";
import {useAuth} from "../hooks/authContext";
import CustomTable from "../components/CustomTable";

function isValidKey(str) {
    return /^[a-zA-Z0-9._-]+$/.test(str);
}

function slugify(key) {
    return key.split(".").pop().toLowerCase();
}

function inheritHref(parentHref, childKey) {
    return `${parentHref}/${slugify(childKey)}`;
}

export default function HeaderMenu() {
    const API_URL = process.env.REACT_APP_API_URL || "/api";

    const [menu, setMenu] = useState([]);
    const [editing, setEditing] = useState(null);
    const [creating, setCreating] = useState(false);

    const {pushSnapshot, undo, canUndo} = useAuditLog([]);
    const {showToast} = useToast();
    const {accessToken, user} = useAuth();

    const canEdit = user && (user.role === "moderator" || user.role === "admin");

    useEffect(() => {
        async function load() {
            if (!accessToken) return;
            const res = await fetch(`${API_URL}/header-menu`, {
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (res.ok) {
                const data = await res.json();
                setMenu(data);
            }
        }
        load();
    }, [accessToken]);

    async function saveMenu(next) {
        await fetch(`${API_URL}/header-menu`, {
            method: "PATCH",
            headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${accessToken}`,
            },
            body: JSON.stringify({json: next}),
        });
        setMenu(next);
        pushSnapshot(next, null, "Меню обновлено");
        showToast("Меню сохранено");
    }

    async function ensureTranslationKey(key) {
        if (!isValidKey(key)) {
            showToast("Некорректный ключ перевода");
            return;
        }
        try {
            await fetch(`${API_URL}/translations/bulk-update`, {
                method: "PATCH",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${accessToken}`,
                },
                body: JSON.stringify({
                    items: [
                        {key, lang: "ru", value: ""},
                        {key, lang: "en", value: ""},
                    ],
                }),
            });
        } catch {
            // игнорируем ошибки
        }
    }

    function normalizeItem(item, parentHref = "") {
        if (!isValidKey(item.label)) {
            showToast(`Некорректный ключ: ${item.label}`);
        } else {
            ensureTranslationKey(item.label);
        }

        if (!item.href) {
            item.href = parentHref
                ? inheritHref(parentHref, item.label)
                : `/${slugify(item.label)}`;
        }

        if (item.items) {
            item.items = item.items.map((sub) =>
                normalizeItem(sub, item.href)
            );
        }
        if (item.columns) {
            item.columns = item.columns.map((col) => ({
                ...col,
                title: col.title,
                items: col.items.map((sub) =>
                    normalizeItem(sub, item.href)
                ),
            }));
        }
        return item;
    }

    function updateItem(index, updated) {
        const next = [...menu];
        next[index] = normalizeItem(updated);
        saveMenu(next);
    }

    function deleteItem(index) {
        const next = menu.filter((_, i) => i !== index);
        saveMenu(next);
    }

    function addItem(item) {
        const next = [...menu, normalizeItem(item)];
        saveMenu(next);
    }

    return (
        <div className="page" style={{padding: 24}}>
            <div className="page__header">
                <h1>Хедер‑меню</h1>

                {canEdit && (
                    <div style={{display: "flex", gap: 12}}>
                        <button
                            className="button button_icon button_border"
                            style={{color: "var(--color-error)"}}
                            disabled={!canUndo}
                            onClick={undo}
                        >
                            <FiRotateCcw size={16}/>
                        </button>

                        <button
                            className="button"
                            onClick={() => setCreating(true)}
                        >
                            Добавить
                        </button>
                    </div>
                )}
            </div>

            <CustomTable
                columns={[
                    {key: "type", title: "Тип"},
                    {
                        key: "label",
                        title: "Ключ",
                        render: (value) => (
                            <a
                                href={`/?key=${value}`}
                                className="table__cell-text"
                                style={{color: "var(--color-link)"}}
                            >
                                {value}
                            </a>
                        ),
                    },
                    {
                        key: "actions",
                        title: "Действия",
                        render: (_, item, index) =>
                            canEdit && (
                                <span style={{display: "flex", gap: 8}}>
                        <button
                            className="button button_icon button_reject"
                            onClick={() => setEditing({index, item})}
                        >
                          <FiEdit size={16}/>
                        </button>
                        <button
                            className="button button_icon button_reject"
                            onClick={() => deleteItem(index)}
                        >
                          <FiTrash size={16}/>
                        </button>
                      </span>
                            ),
                    },
                ]}
                data={menu}
            />

            {creating && canEdit && (
                <MenuItemDialog
                    title="Добавить пункт меню"
                    onSave={addItem}
                    onClose={() => setCreating(false)}
                />
            )}

            {editing && canEdit && (
                <MenuItemDialog
                    title="Редактировать пункт"
                    initial={editing.item}
                    onSave={(updated) => updateItem(editing.index, updated)}
                    onClose={() => setEditing(null)}
                />
            )}
        </div>
    );
}
