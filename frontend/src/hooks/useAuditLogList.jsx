import { useState, useCallback } from "react";

export function useAuditLogList(initial = []) {
    const [state, setState] = useState(initial);
    const [history, setHistory] = useState([]);

    const pushSnapshot = useCallback((next, meta, label) => {
        setHistory(h => [...h, { state: structuredClone(state), meta, label }]);
        setState(next);
    }, [state]);

    const undo = useCallback(() => {
        setHistory(h => {
            if (h.length === 0) return h;
            const last = h[h.length - 1];
            setState(last.state);
            return h.slice(0, -1);
        });
    }, []);

    return {
        state,
        setState,
        pushSnapshot,
        undo,
        canUndo: history.length > 0,
    };
}
