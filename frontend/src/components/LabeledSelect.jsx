export default function LabeledSelect({
                                          label,
                                          value,
                                          onChange,
                                          options = [],
                                          className = "",
                                          placeholder = null,
                                      }) {
    return (
        <div className={`select field-holder ${className}`}>
            {label && (
                <span className="field-holder__label">
                    {label}
                </span>
            )}

            <select
                className="field-holder__input"
                value={value}
                onChange={(e) => onChange(e.target.value)}
            >
                {placeholder && (
                    <option value="" disabled>
                        {placeholder}
                    </option>
                )}

                {options.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                        {opt.label}
                    </option>
                ))}
            </select>
        </div>
    );
}
