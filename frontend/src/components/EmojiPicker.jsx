import EmojiPicker from "emoji-picker-react";

export default function EmojiPickerPopup({ onSelect }) {
    return (
        <div
            style={{
                position: "absolute",
                zIndex: 20,
                right: 0,
                top: "40px",
            }}
        >
            <EmojiPicker
                theme="dark"
                onEmojiClick={(emoji) => onSelect(emoji.emoji)}
            />
        </div>
    );
}
