import { useRef, useState } from "react";

export default function LabeledFileInput({
                                             label,
                                             onChange,
                                             multiple = false,
                                             accept = "",
                                             className = "",
                                         }) {
    const inputRef = useRef(null);
    const [files, setFiles] = useState([]);

    function handleSelect(e) {
        const list = Array.from(e.target.files || []);
        setFiles(list);
        onChange(e.target.files);
    }

    return (
        <div className={`field-holder ${className}`}>
            {label && <span className="field-holder__label">{label}</span>}

            <button
                type="button"
                className="file-input"
                onClick={() => inputRef.current?.click()}
            >
        <span className="file-input__text">
          {files.length ? files.map(f => f.name).join(", ") : "Выберите файл"}
        </span>
                <span className="file-input__btn">Обзор</span>
            </button>

            <input
                ref={inputRef}
                type="file"
                multiple={multiple}
                accept={accept}
                onChange={handleSelect}
                style={{ display: "none" }}
            />
        </div>
    );
}
