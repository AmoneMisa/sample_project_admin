import {useEffect, useState} from "react";
import ConfirmDialog from "../components/ConfirmDialog";
import TestimonialDialog from "../components/TestimonialDialog";
import {useToast} from "../components/ToastContext";
import {FiCopy, FiEdit, FiRotateCcw, FiTrash} from "react-icons/fi";
import Checkbox from "../components/Checkbox";
import {useAuditLogList} from "../hooks/useAuditLogList";
import {useAuth} from "../hooks/authContext";
import CustomTable from "../components/CustomTable";

export default function Testimonials() {
    const API_URL = process.env.REACT_APP_API_URL || "/api";

    const [items, setItems] = useState([]);
    const [editing, setEditing] = useState(null);
    const [creating, setCreating] = useState(false);
    const [deleteTarget, setDeleteTarget] = useState(null);
    const {state, setState, pushSnapshot, undo, canUndo} = useAuditLogList([]);
    const {showToast} = useToast();
    const {accessToken, user} = useAuth();
    const canEdit = user && (user.role === "moderator" || user.role === "admin");

    useEffect(() => {
        async function load() {
            if (!accessToken) return;
            const res = await fetch(`${API_URL}/testimonials`, {headers: {Authorization: `Bearer ${accessToken}`},});
            if (res.ok) {
                const data = await res.json();
                setItems(data);
                setState(data);
            }
        }

        load();
    }, [accessToken]);

    async function createItem(payload) {
        const res = await fetch(`${API_URL}/testimonials`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${accessToken}`,
            },
            body: JSON.stringify(payload),
        });
        const newItem = await res.json();

        const next = [...items, newItem];
        pushSnapshot(next, null, "Создан отзыв");
        setItems(next);
        setState(next);
        showToast("Отзыв создан");
    }

    async function updateItem(id, payload) {
        const res = await fetch(`${API_URL}/testimonials/${id}`, {
            method: "PATCH",
            headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${accessToken}`,
            },
            body: JSON.stringify(payload),
        });
        const updated = await res.json();

        const next = items.map(i => (i.id === id ? updated : i));
        pushSnapshot(next, null, "Обновлён отзыв");
        setItems(next);
        setState(next);
        showToast("Отзыв обновлён");
    }

    async function deleteItem(id) {
        await fetch(`${API_URL}/testimonials/${id}`, {
            method: "DELETE",
            headers: {
                Authorization: `Bearer ${accessToken}`,
            },
        });

        const next = items.filter(i => i.id !== id);
        pushSnapshot(next, null, "Удалён отзыв");
        setItems(next);
        setState(next);
        showToast("Отзыв удалён");
    }

    async function duplicateItem(item) {
        const {id, ...rest} = item;
        const duplicated = {
            ...rest,
            name: `${item.name} (копия)`,
        };

        const res = await fetch(`${API_URL}/testimonials`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${accessToken}`,
            },
            body: JSON.stringify(duplicated),
        });

        const newItem = await res.json();

        const next = [...items, newItem];
        pushSnapshot(next, null, `Продублирован отзыв #${item.id}`);
        setItems(next);
        setState(next);
        showToast("Отзыв продублирован");
    }

    return (
        <div className="page" style={{padding: 24}}>
            <div className="page__header">
                <h1>Отзывы</h1>

                <div style={{display: "flex", gap: 12}}>
                    {canEdit && (
                        <>
                            <button
                                className="button button_icon button_border"
                                disabled={!canUndo}
                                onClick={undo}
                                style={{color: "var(--color-error)"}}
                            >
                                <FiRotateCcw size={16}/> Отменить
                            </button>

                            <button
                                className="button"
                                onClick={() => setCreating(true)}
                            >
                                Создать отзыв
                            </button>
                        </>
                    )}
                </div>
            </div>
            <CustomTable
                columns={[
                    {key: "id", title: "ID"},
                    {key: "name", title: "Имя"},
                    {key: "role", title: "Роль"},
                    {key: "quote", title: "Отзыв"},
                    {key: "rating", title: "Рейтинг", width: "100px"},
                    {
                        key: "isVisible",
                        title: "Отображать",
                        width: "120px",
                        render: (value, row) =>
                            canEdit ? (
                                <Checkbox
                                    checked={value}
                                    onChange={() => updateItem(row.id, {isVisible: !value})}
                                />
                            ) : (
                                <Checkbox checked={value} disabled/>
                            ),
                    },
                    {
                        key: "actions",
                        title: "Действия",
                        width: "180px",
                        render: (_, row) =>
                            canEdit && (
                                <div style={{display: "flex", justifyContent: "space-between"}}>
                                    <button
                                        className="button button_icon button_reject"
                                        onClick={() => setEditing(row)}
                                    >
                                        <FiEdit size={16}/>
                                    </button>
                                    <button
                                        className="button button_icon button_reject"
                                        onClick={() => setDeleteTarget(row.id)}
                                    >
                                        <FiTrash size={16}/>
                                    </button>
                                    <button
                                        className="button button_icon button_reject"
                                        onClick={() => duplicateItem(row)}
                                    >
                                        <FiCopy size={16}/>
                                    </button>
                                </div>
                            ),
                    },
                ]}
                data={items}
            />

            {creating && canEdit && (
                <TestimonialDialog
                    title="Создать отзыв"
                    onSave={createItem}
                    onClose={() => setCreating(false)}
                />
            )}

            {editing && canEdit && (
                <TestimonialDialog
                    title="Редактировать отзыв"
                    initial={editing}
                    onSave={(payload) => updateItem(editing.id, payload)}
                    onClose={() => setEditing(null)}
                />
            )}

            {deleteTarget && canEdit && (
                <ConfirmDialog
                    open={true}
                    title="Удалить отзыв?"
                    text="Вы уверены, что хотите удалить этот отзыв?"
                    onConfirm={() => {
                        deleteItem(deleteTarget);
                        setDeleteTarget(null);
                    }}
                    onCancel={() => setDeleteTarget(null)}
                />
            )}
        </div>
    );
}
