import { createContext, useContext, useState } from "react";

const ToastContext = createContext(null);

export function ToastProvider({ children }) {
    const [messages, setMessages] = useState([]);

    function showToast(text) {
        const id = Date.now();
        setMessages((prev) => [...prev, { id, text }]);
        setTimeout(() => {
            setMessages((prev) => prev.filter((m) => m.id !== id));
        }, 2500);
    }

    return (
        <ToastContext.Provider value={{ showToast }}>
            {children}

            <div className="toast-container">
                {messages.map((m) => (
                    <div key={m.id} className="toast">
                        {m.text}
                    </div>
                ))}
            </div>
        </ToastContext.Provider>
    );
}

export function useToast() {
    return useContext(ToastContext);
}
