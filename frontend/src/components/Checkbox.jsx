export default function Checkbox({
                                     label,
                                     checked,
                                     onChange,
                                     className = "",
                                     disabled = false,
                                 }) {
    return (
        <label className={`checkbox ${className}`}>
            <input
                type="checkbox"
                checked={checked}
                onChange={onChange}
                disabled={disabled}
            />
            <span className="checkbox__box"></span>
            {label && <span className="checkbox__label">{label}</span>}
        </label>
    );
}
