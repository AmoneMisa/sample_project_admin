import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "translationHistory";

export function useAuditLog() {
    const [translations, setTranslations] = useState({});
    const [meta, setMeta] = useState({});
    const [history, setHistory] = useState([]);
    const [canUndo, setCanUndo] = useState(false);
    const [lastDeleted, setLastDeleted] = useState(null);

    // LOAD HISTORY
    useEffect(() => {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return;

        try {
            const parsed = JSON.parse(raw);
            if (Array.isArray(parsed)) {
                setHistory(parsed.slice(-20));
                setCanUndo(parsed.length > 0);
            }
        } catch (e) {
            console.error("Ошибка при загрузке истории:", e);
        }
    }, []);

    const persistHistory = (next) => {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(next.slice(-20)));
        } catch (e) {
            console.error("Ошибка при сохранении истории:", e);
        }
    };

    // SAVE SNAPSHOT
    const pushSnapshot = useCallback(
        (event) => {
            const snapshot = {
                translations: structuredClone(translations),
                meta: structuredClone(meta),
                event,
                timestamp: Date.now(),
            };

            const nextHistory = [...history.slice(-19), snapshot];

            setHistory(nextHistory);
            persistHistory(nextHistory);
            setCanUndo(true);
        },
        [translations, meta, history]
    );

    // UNDO
    const undo = useCallback(() => {
        if (!history.length) return;

        const last = history[history.length - 1];
        const nextHistory = history.slice(0, -1);

        setHistory(nextHistory);
        persistHistory(nextHistory);

        setTranslations(structuredClone(last.translations));
        setMeta(structuredClone(last.meta));

        setCanUndo(nextHistory.length > 0);
    }, [history]);

    const getHistory = useCallback(() => history, [history]);

    const markDeleted = useCallback((key, translationsForKey, metaForKey) => {
        setLastDeleted({
            key,
            translationsForKey: structuredClone(translationsForKey),
            metaForKey: structuredClone(metaForKey),
        });
    }, []);

    const restoreLastDeleted = useCallback(() => {
        if (!lastDeleted) return null;

        const ld = lastDeleted;
        setLastDeleted(null);

        return {
            key: ld.key,
            translationsForKey: structuredClone(ld.translationsForKey),
            metaForKey: structuredClone(ld.metaForKey),
        };
    }, [lastDeleted]);

    return {
        translations,
        setTranslations,
        meta,
        setMeta,
        pushSnapshot,
        undo,
        canUndo,
        getHistory,
        markDeleted,
        restoreLastDeleted,
    };
}
