export default function ConfirmDialog({ open, title, text, onConfirm, onCancel }) {
    if (!open) return null;

    return (
        <div className="modal-backdrop">
            <div className="modal">
                <h3>{title}</h3>
                <p>{text}</p>
                <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
                    <button className="button button_accept" onClick={onConfirm}>Да</button>
                    <button className="button button_reject" onClick={onCancel}>Отмена</button>
                </div>
            </div>
        </div>
    );
}
