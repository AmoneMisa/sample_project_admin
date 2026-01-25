export function transliterate(str) {
    const map = {
        а: "a", б: "b", в: "v", г: "g", д: "d",
        е: "e", ё: "e", ж: "zh", з: "z", и: "i",
        й: "i", к: "k", л: "l", м: "m", н: "n",
        о: "o", п: "p", р: "r", с: "s", т: "t",
        у: "u", ф: "f", х: "h", ц: "ts", ч: "ch",
        ш: "sh", щ: "shch", ы: "y", э: "e", ю: "yu", я: "ya"
    };
    return str
        .toLowerCase()
        .split("")
        .map(ch => map[ch] || ch)
        .join("")
        .replace(/\s+/g, "-")
        .replace(/[^a-z0-9-]/g, "");
}
