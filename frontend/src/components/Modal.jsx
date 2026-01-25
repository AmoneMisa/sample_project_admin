import { useEffect, useRef } from "react";
import { FiPlus } from "react-icons/fi";

export default function Modal({
                                  open,
                                  title,
                                  children,
                                  onClose,
                                  width = 500,
                                  closeOnBackdrop = true,
                              }) {
    const backdropRef = useRef(null);

    useEffect(() => {
        if (!open) return;

        function handleKey(e) {
            if (e.key === "Escape") onClose();
        }

        window.addEventListener("keydown", handleKey);
        return () => window.removeEventListener("keydown", handleKey);
    }, [open, onClose]);

    if (!open) return null;

    return (
        <div
            ref={backdropRef}
            className="modal-backdrop"
            onMouseDown={(e) => {
                if (closeOnBackdrop && e.target === backdropRef.current) {
                    onClose();
                }
            }}
        >
            <div
                className="modal"
                style={{ width }}
                onMouseDown={(e) => e.stopPropagation()} // блокируем всплытие
            >
                <button
                    style={{ rotate: "45deg" }}
                    className="modal__cross button button_icon button_reject"
                    onClick={onClose}
                >
                    <FiPlus size={24} />
                </button>

                {title && <h3 className="modal__header">{title}</h3>}

                <div className="modal__content scrollbar">{children}</div>
            </div>
        </div>
    );
}
