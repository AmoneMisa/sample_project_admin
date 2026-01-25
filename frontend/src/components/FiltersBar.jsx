import LabeledInput from "./LabeledInput";
import LabeledSelect from "./LabeledSelect";

export default function FiltersPanel({
                                         search,
                                         setSearch,
                                         filterStatus,
                                         setFilterStatus,
                                         filterErrorLevel,
                                         setFilterErrorLevel,
                                     }) {
    return (
        <div style={{display: "flex", gap: 12}}>
            <LabeledInput
                label="Поиск"
                placeholder="Ключ или значение"
                value={search}
                onChange={setSearch}
            />

            <LabeledSelect
                label="Статус:"
                value={filterStatus}
                onChange={setFilterStatus}
                options={[
                    {value: "all", label: "Все"},
                    {value: "complete", label: "Полные"},
                    {value: "incomplete", label: "Неполные"},
                ]}
            />

            <LabeledSelect
                label="Ошибки:"
                value={filterErrorLevel}
                onChange={(e) => setFilterErrorLevel(e.target.value)}
                options={[
                    {value: "all", label: "Все"},
                    {value: "error", label: "Пустые"},
                    {value: "warning", label: "Частично заполненные"},
                ]}
            />
        </div>
    );
}
