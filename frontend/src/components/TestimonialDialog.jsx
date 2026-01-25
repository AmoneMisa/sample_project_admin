import {useState} from "react";
import Modal from "./Modal";
import LabeledInput from "./LabeledInput";
import Checkbox from "./Checkbox";

export default function TestimonialDialog({title, initial, onSave, onClose}) {
    const [name, setName] = useState(initial?.name || "");
    const [role, setRole] = useState(initial?.role || "");
    const [quote, setQuote] = useState(initial?.quote || "");
    const [rating, setRating] = useState(initial?.rating || 5);
    const [avatar, setAvatar] = useState(initial?.avatar || "");
    const [logo, setLogo] = useState(initial?.logo || "");
    const [isVisible, setIsVisible] = useState(initial?.isVisible ?? true);

    return (
        <Modal open={true} title={title} onClose={onClose} width={500}>
            <LabeledInput
                label="Имя"
                value={name}
                onChange={(e) => setName(e.target.value)}
            />

            <LabeledInput
                label="Роль"
                value={role}
                onChange={(e) => setRole(e.target.value)}
            />

            <label className="field-holder">
                <span className="field-holder__label">Отзыв</span>
                <textarea
                    className="field-holder__input"
                    style={{padding: 6, minHeight: 80}}
                    value={quote}
                    onChange={(e) => setQuote(e.target.value)}
                />
            </label>

            <LabeledInput
                label="Рейтинг"
                type="number"
                value={rating}
                max={5}
                onChange={(e) => setRating(Number(e.target.value))}
            />

            <LabeledInput
                label="Avatar URL"
                value={avatar}
                onChange={(e) => setAvatar(e.target.value)}
            />

            <LabeledInput
                label="Logo URL"
                value={logo}
                onChange={(e) => setLogo(e.target.value)}
            />

            <Checkbox
                label="Показывать"
                checked={isVisible}
                onChange={() => setIsVisible(!isVisible)}
            />
            <button
                className="button button_accept"
                onClick={() => {
                    onSave({name, role, quote, rating, avatar, logo, isVisible});
                    onClose();
                }}
            >
                Сохранить
            </button>
        </Modal>
    );
}
