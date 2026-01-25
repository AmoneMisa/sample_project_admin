import Modal from "./Modal";

export default function HistoryDialog({open, history, onRestore, onClose}) {
    if (!open) return null;

    return (
        <Modal open={open} title="История изменений" onClose={onClose} width={600}>
            <ul className="modal__list scrollbar">
                {history.map((h, idx) => (
                    <li key={idx} className="modal__list-item">
                        <div>{idx + 1}. {h.event}</div>
                        <button onClick={() => onRestore(idx)}>Восстановить</button>
                    </li>
                ))}
            </ul>
        </Modal>
    );
}
