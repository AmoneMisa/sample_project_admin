import { useState } from "react";
import Modal from "./Modal";
import LabeledInput from "./LabeledInput";
import LabeledSelect from "./LabeledSelect";
import DropdownSimpleEditor from "./DropdownSimpleEditor";
import MegaMenuEditor from "./MegaMenuEditor";

function isValidKey(str) {
    return /^[a-zA-Z0-9._-]+$/.test(str);
}

function slugify(key) {
    return key.split(".").pop().toLowerCase();
}

export default function MenuItemDialog({ title, initial, onSave, onClose, parentKey, parentHref }) {
    const [type, setType] = useState(initial?.type || "simple");
    const [label, setLabel] = useState(initial?.label || (parentKey ? `${parentKey}.newItem` : ""));
    const [href, setHref] = useState(initial?.href || "");
    const [items, setItems] = useState(initial?.items || []);
    const [columns, setColumns] = useState(initial?.columns || []);
    const [image, setImage] = useState(initial?.image || { src: "", position: "right" });
    const [error, setError] = useState("");

    function handleSave() {
        if (!isValidKey(label)) {
            setError("Ключ может содержать только латиницу, цифры, точки, дефисы и подчёркивания");
            return;
        }

        const item = { type, label };

        if (type === "simple") {
            item.href = href || `/${slugify(label)}`;
        }

        if (type === "dropdown-simple") {
            item.items = items.map(sub => ({
                ...sub,
                href: sub.href || (href ? `${href}/${slugify(sub.label)}` : `/${slugify(sub.label)}`)
            }));
        }

        if (type === "dropdown-mega") {
            item.columns = columns.map(col => ({
                ...col,
                items: col.items.map(sub => ({
                    ...sub,
                    href: sub.href || (href ? `${href}/${slugify(sub.label)}` : `/${slugify(sub.label)}`)
                }))
            }));
            item.image = image;
        }

        onSave(item);
        onClose();
    }

    return (
        <Modal open={true} title={title} onClose={onClose} width={600}>
            <LabeledSelect
                label="Тип"
                value={type}
                onChange={setType}
                options={[
                    { value: "simple", label: "Ссылка" },
                    { value: "dropdown-simple", label: "Одиночный список" },
                    { value: "dropdown-mega", label: "Таблица списков" },
                ]}
            />

            <LabeledInput
                label="Ключ меню"
                title="Введите ключ перевода. Заполните переводы на странице переводов."
                value={label}
                onChange={setLabel}
            />
            {error && <div className="field-error">{error}</div>}

            {type === "simple" && (
                <LabeledInput
                    label="Ссылка"
                    title="Если оставить пустым, будет сгенерирована автоматически"
                    value={href}
                    onChange={setHref}
                />
            )}

            {type === "dropdown-simple" && (
                <DropdownSimpleEditor items={items} onChange={setItems} />
            )}

            {type === "dropdown-mega" && (
                <MegaMenuEditor
                    columns={columns}
                    image={image}
                    onChange={({ columns, image }) => {
                        setColumns(columns);
                        setImage(image);
                    }}
                />
            )}

            <button className="button button_accept" onClick={handleSave}>
                Сохранить
            </button>
        </Modal>
    );
}
