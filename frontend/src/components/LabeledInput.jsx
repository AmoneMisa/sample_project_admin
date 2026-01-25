export default function LabeledInput({
                                         label,
                                         placeholder = "",
                                         value,
                                         title = "",
                                         onChange,
                                         max = 5,
                                         type = "text",
                                         className = "",
                                     }) {
    return (
        <label className="field-holder">
            {label && <span className="field-holder__label">{label}</span>}
            <input
                type={type}
                value={value}
                placeholder={placeholder}
                onChange={(e) => onChange(e.target.value)}
                className={className + " field-holder__input"}
                style={{padding: 6}}
                max={max}
                min={1}
                title={title}
            />
        </label>
    );
}
