export default function CustomTable({ columns, data }) {
    return (
        <table className="table" style={{ width: "100%", marginTop: 20 }}>
            <thead>
            <tr className="table__header-row">
                {columns.map(col => (
                    <th
                        key={col.key}
                        className="table__header"
                        style={col.width ? { width: col.width } : {}}
                    >
                            <span className="table__header-text gradient-text">
                                {col.title}
                            </span>
                    </th>
                ))}
            </tr>
            </thead>
            <tbody>
            {data.map((row, rowIndex) => (
                <tr key={row.id || rowIndex} className="table__row">
                    {columns.map(col => (
                        <td
                            key={col.key}
                            className="table__cell"
                            style={col.width ? { width: col.width } : {}}
                        >
                                <span className="table__cell-text">
                                    {col.render
                                        ? col.render(row[col.key], row, rowIndex)
                                        : row[col.key]}
                                </span>
                        </td>
                    ))}
                </tr>
            ))}
            </tbody>
        </table>
    );
}
