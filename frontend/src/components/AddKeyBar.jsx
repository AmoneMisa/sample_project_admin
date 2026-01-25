import {useState} from "react";
import LabeledInput from "./LabeledInput";

export default function AddKeyBar({onAdd, existingKeys}) {
    const [newKey, setNewKey] = useState("");
    const [error, setError] = useState("");

    function handleAdd() {
        const key = newKey.trim();
        if (!key) return;
        if (existingKeys.includes(key)) {
            setError("Такой ключ уже существует");
            return;
        }
        onAdd(key);
        setNewKey("");
        setError("");
    }

    return (
        <div className={'field'}>
            <LabeledInput
                label="Новый ключ"
                placeholder="Новый ключ"
                value={newKey}
                onChange={(val) => {
                    setNewKey(val);
                    setError("");
                }}
            />

            <button className="button" onClick={handleAdd}>Добавить</button>
            {error && (<span style={{color: "var(--color-error)", marginLeft: 8}}>
          {error}
        </span>)}
        </div>
    );
}
