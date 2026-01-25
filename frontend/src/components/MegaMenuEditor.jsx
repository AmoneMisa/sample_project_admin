import { useState } from "react";
import { FiPlus, FiTrash } from "react-icons/fi";
import LabeledInput from "./LabeledInput";
import LabeledSelect from "./LabeledSelect";

export default function MegaMenuEditor({ columns = [], image, onChange, parentKey = "headerMenu", parentHref = "" }) {
    const [localColumns, setLocalColumns] = useState(columns);
    const [localImage, setLocalImage] = useState(image || { src: "", position: "right" });

    function isValidKey(str) {
        return /^[a-z0-9._-]+$/.test(str);
    }

    function slugify(key) {
        return key.split(".").pop().toLowerCase();
    }

    function inheritHref(parent, childKey) {
        return parent ? `${parent}/${slugify(childKey)}` : `/${slugify(childKey)}`;
    }

    // -----------------------------
    // COLUMN TITLE
    // -----------------------------
    function updateColumn(index, field, value) {
        const next = [...localColumns];
        let updated = { ...next[index], [field]: value };

        if (field === "title") {
            if (!isValidKey(value)) {
                updated.errorTitle = "Ключ может содержать только латиницу, цифры, точки, дефисы и подчёркивания";
            } else {
                delete updated.errorTitle;

                // автогенерация иерархии ключей
                if (!updated.title.startsWith(parentKey)) {
                    updated.title = `${parentKey}.${value}`;
                }
            }
        }

        next[index] = updated;
        setLocalColumns(next);
        onChange({ columns: next, image: localImage });
    }

    // -----------------------------
    // COLUMN ITEM
    // -----------------------------
    function updateItem(colIndex, itemIndex, field, value) {
        const next = [...localColumns];
        const items = [...next[colIndex].items];
        let updated = { ...items[itemIndex], [field]: value };

        const colKey = next[colIndex].title || parentKey;
        const colHref = next[colIndex].href || parentHref;

        if (field === "label") {
            if (!isValidKey(value)) {
                updated.errorLabel = "Ключ может содержать только латиницу, цифры, точки, дефисы и подчёркивания";
            } else {
                delete updated.errorLabel;

                // иерархия ключей: parent.child
                if (!updated.label.startsWith(colKey)) {
                    updated.label = `${colKey}.${value}`;
                }
            }

            // автогенерация href
            if (!updated.href) {
                updated.href = inheritHref(colHref, updated.label);
            }
        }

        if (field === "badge") {
            if (!isValidKey(value)) {
                updated.errorBadge = "Ключ может содержать только латиницу, цифры, точки, дефисы и подчёркивания";
            } else {
                delete updated.errorBadge;
            }
        }

        if (field === "href" && !value) {
            updated.href = inheritHref(colHref, updated.label);
        }

        items[itemIndex] = updated;
        next[colIndex].items = items;

        setLocalColumns(next);
        onChange({ columns: next, image: localImage });
    }

    // -----------------------------
    // ADD / DELETE
    // -----------------------------
    function addColumn() {
        const next = [...localColumns, { title: `${parentKey}.newColumn`, items: [] }];
        setLocalColumns(next);
        onChange({ columns: next, image: localImage });
    }

    function deleteColumn(index) {
        const next = localColumns.filter((_, i) => i !== index);
        setLocalColumns(next);
        onChange({ columns: next, image: localImage });
    }

    function addItem(colIndex) {
        const colKey = localColumns[colIndex].title || parentKey;
        const next = [...localColumns];

        next[colIndex].items.push({
            label: `${colKey}.newItem`,
            href: "",
            badge: ""
        });

        setLocalColumns(next);
        onChange({ columns: next, image: localImage });
    }

    function deleteItem(colIndex, itemIndex) {
        const next = [...localColumns];
        next[colIndex].items = next[colIndex].items.filter((_, i) => i !== itemIndex);
        setLocalColumns(next);
        onChange({ columns: next, image: localImage });
    }

    // -----------------------------
    // IMAGE
    // -----------------------------
    function updateImage(field, value) {
        const next = { ...localImage, [field]: value };
        setLocalImage(next);
        onChange({ columns: localColumns, image: next });
    }

    // -----------------------------
    // RENDER
    // -----------------------------
    return (
        <div className="editor">
            <div>Колонки</div>

            {localColumns.map((col, colIndex) => (
                <div key={colIndex} className="editor__column">
                    <LabeledInput
                        title="Введите ключ перевода. Заполните переводы на странице переводов."
                        label="Заголовок"
                        value={col.title}
                        onChange={(val) => updateColumn(colIndex, "title", val)}
                    />
                    {col.errorTitle && <div className="field-error">{col.errorTitle}</div>}

                    {col.items.map((item, itemIndex) => (
                        <div key={itemIndex} className="editor__row">
                            <LabeledInput
                                label="Ключ категории"
                                title="Введите ключ перевода. Заполните переводы на странице переводов."
                                value={item.label}
                                onChange={(val) => updateItem(colIndex, itemIndex, "label", val)}
                            />
                            {item.errorLabel && <div className="field-error">{item.errorLabel}</div>}

                            <LabeledInput
                                label="Ссылка"
                                title="Если оставить поле пустым, ссылка будет сгенерирована автоматически"
                                value={item.href}
                                onChange={(val) => updateItem(colIndex, itemIndex, "href", val)}
                            />

                            <LabeledInput
                                label="Ключ бейджа"
                                title="Введите ключ перевода. Заполните переводы на странице переводов."
                                value={item.badge}
                                onChange={(val) => updateItem(colIndex, itemIndex, "badge", val)}
                            />
                            {item.errorBadge && <div className="field-error">{item.errorBadge}</div>}

                            <button
                                className="button button_icon button_reject"
                                onClick={() => deleteItem(colIndex, itemIndex)}
                            >
                                <FiTrash />
                            </button>
                        </div>
                    ))}

                    <div className="editor__buttons">
                        <button className="button button_border button_icon" onClick={() => addItem(colIndex)}>
                            <FiPlus /> пункт
                        </button>
                        <button className="button button_icon button_border button_reject" onClick={() => deleteColumn(colIndex)}>
                            <FiTrash /> колонку
                        </button>
                    </div>
                </div>
            ))}

            <button className="button button_border button_icon" onClick={addColumn}>
                <FiPlus /> колонку
            </button>

            <div>Изображение</div>

            <LabeledInput
                label="SRC"
                value={localImage.src}
                onChange={(val) => updateImage("src", val)}
            />

            <LabeledSelect
                label="Расположение"
                value={localImage.position}
                onChange={(val) => updateImage("position", val)}
                options={[
                    { value: "right", label: "Справа" },
                    { value: "left", label: "Слева" }
                ]}
            />
        </div>
    );
}
