import {useState} from "react";
import LabeledInput from "../components/LabeledInput";
import LabeledSelect from "../components/LabeledSelect";
import {useAuth} from "../hooks/authContext";
import CustomTable from "../components/CustomTable";

const API_URL = process.env.REACT_APP_API_URL;

export default function UsersPage() {
    const {accessToken} = useAuth();

    const [users, setUsers] = useState([]);
    const [roleFilter, setRoleFilter] = useState("");
    const [search, setSearch] = useState("");


    async function loadUsers() {
        const url = roleFilter && roleFilter !== "all"
            ? `${API_URL}/users/by-role/${roleFilter}`
            : `${API_URL}/users`;

        const res = await fetch(url, {
            headers: {Authorization: `Bearer ${accessToken}`},
        });

        const data = await res.json();
        setUsers(data);
    }

    async function changeRole(id, role) {
        await fetch(`${API_URL}/users/${id}/role`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${accessToken}`,
            },
            body: JSON.stringify({role}),
        });
        loadUsers();
    }

    async function deleteUser(id) {
        await fetch(`${API_URL}/users/${id}/delete`, {
            method: "POST",
            headers: {Authorization: `Bearer ${accessToken}`},
        });
        loadUsers();
    }

    async function restoreUser(id) {
        await fetch(`${API_URL}/users/${id}/restore`, {
            method: "POST",
            headers: {Authorization: `Bearer ${accessToken}`},
        });
        loadUsers();
    }

    const filtered = users.filter((u) =>
        u.email.toLowerCase().includes(search.toLowerCase())
    );

    const columns = [
        {key: "id", title: "ID"},
        {key: "email", title: "Email"},
        {key: "full_name", title: "ФИО"},
        {key: "role", title: "Роль"},
        {
            key: "actions",
            title: "Действия",
            render: (_, u) => (
                <span style={{display: "flex", gap: 8}}>
                    {u.role !== "admin" && (
                        <>
                            <button
                                className="button_border"
                                onClick={() =>
                                    changeRole(
                                        u.id,
                                        u.role === "observer"
                                            ? "moderator"
                                            : "observer"
                                    )
                                }
                            >
                                {u.role === "observer"
                                    ? "Сделать модератором"
                                    : "Сделать наблюдателем"}
                            </button>

                            {!u.deleted ? (
                                <button
                                    className="button_reject"
                                    onClick={() => deleteUser(u.id)}
                                >
                                    Удалить
                                </button>
                            ) : (
                                <button
                                    className="button_accept"
                                    onClick={() => restoreUser(u.id)}
                                >
                                    Восстановить
                                </button>
                            )}
                        </>
                    )}
                </span>
            ),
        },
    ];

    return (
        <div className='page' style={{padding: 24, fontFamily: "sans-serif"}}>
            <div className="page__header">
                <h2 className="gradient-text" style={{marginBottom: 24}}>
                    Управление пользователями
                </h2>

                <div className="field" style={{marginBottom: 20}}>
                    <LabeledInput
                        label="Поиск"
                        value={search}
                        onChange={setSearch}
                    />

                    <LabeledSelect
                        value={roleFilter}
                        onChange={(e) => setRoleFilter(e.target.value)}
                        options={[
                            {value: "all", label: "Все"},
                            {value: "observer", label: "Наблюдатели"},
                            {value: "moderator", label: "Модераторы"},
                            {value: "admin", label: "Администратор"},
                        ]}
                    />
                </div>
            </div>

            <CustomTable columns={columns} data={filtered}/>
        </div>
    );
}
