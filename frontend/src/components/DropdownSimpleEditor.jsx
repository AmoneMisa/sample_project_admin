import { useState } from "react";
import { FiPlus, FiTrash, FiArrowUp, FiArrowDown } from "react-icons/fi";
import LabeledInput from "./LabeledInput";

function isValidKey(str) {
    return /^[a-zA-Z0-9._-]+$/.test(str);
}

function slugify(key) {
    return key.split(".").pop().toLowerCase();
}

function inheritHref(parentHref, childKey) {
    return `${parentHref}/${slugify(childKey)}`;
}

export default function DropdownSimpleEditor({ items = [], onChange, parentKey = "headerMenu", parentHref = "" }) {
    const [localItems, setLocalItems] = useState(items);

    function update(index, field, value) {
        const next = [...localItems];
        let updated = { ...next[index], [field]: value };

        if (field === "label") {
            if (!isValidKey(value)) {
                updated.errorLabel = "Ключ может содержать только латиницу, цифры, точки, дефисы и подчёркивания";
            } else {
                delete updated.errorLabel;
                // автогенерация дочернего ключа
                if (!updated.label.startsWith(parentKey)) {
                    updated.label = `${parentKey}.${value}`;
                }
            }
            // если href пустой → генерируем из родителя
            if (!updated.href) {
                updated.href = parentHref ? inheritHref(parentHref, updated.label) : `/${slugify(updated.label)}`;
            }
        }

        if (field === "badge") {
            if (!isValidKey(value)) {
                updated.errorBadge = "Ключ может содержать только латиницу, цифры, точки, дефисы и подчёркивания";
            } else {
                delete updated.errorBadge;
            }
        }

        next[index] = updated;
        setLocalItems(next);
        onChange(next);
    }

    function addItem() {
        const next = [
            ...localItems,
            { label: `${parentKey}.newItem`, href: "", badge: "" }
        ];
        setLocalItems(next);
        onChange(next);
    }

    function deleteItem(index) {
        const next = localItems.filter((_, i) => i !== index);
        setLocalItems(next);
        onChange(next);
    }

    function moveItem(index, dir) {
        const next = [...localItems];
        const target = next[index];
        next.splice(index, 1);
        next.splice(index + dir, 0, target);
        setLocalItems(next);
        onChange(next);
    }

    return (
        <div className="editor">
            <div>Пункты меню</div>
            {localItems.map((item, index) => (
                <div key={index} className="editor__row">
                    <LabeledInput
                        title="Введите ключ перевода. Заполните переводы на странице переводов."
                        label="Ключ категории"
                        value={item.label}
                        onChange={(val) => update(index, "label", val)}
                    />
                    {item.errorLabel && <div className="field-error">{item.errorLabel}</div>}

                    <LabeledInput
                        title="Если оставить поле пустым, ссылка будет сгенерирована автоматически"
                        label="Ссылка"
                        value={item.href}
                        onChange={(val) => update(index, "href", val)}
                    />

                    <LabeledInput
                        title="Введите ключ перевода. Заполните переводы на странице переводов."
                        label="Ключ бейджа"
                        value={item.badge}
                        onChange={(val) => update(index, "badge", val)}
                    />
                    {item.errorBadge && <div className="field-error">{item.errorBadge}</div>}

                    <div className="editor__buttons">
                        <button
                            className="button button_icon button_reject"
                            onClick={() => moveItem(index, -1)}
                            disabled={index === 0}
                        >
                            <FiArrowUp />
                        </button>
                        <button
                            className="button button_icon button_reject"
                            onClick={() => moveItem(index, 1)}
                            disabled={index === localItems.length - 1}
                        >
                            <FiArrowDown />
                        </button>
                        <button
                            className="button button_icon button_reject"
                            onClick={() => deleteItem(index)}
                        >
                            <FiTrash />
                        </button>
                    </div>
                </div>
            ))}

            <button className="button button_border button_icon" onClick={addItem}>
                <FiPlus /> пункт
            </button>
        </div>
    );
}
