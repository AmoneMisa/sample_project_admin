import AdminMenu from "./AdminMenu";
import { Outlet } from "react-router-dom";

export default function AdminLayout() {
    return (
        <div className="admin-layout">
            <AdminMenu />
            <div className="admin-content">
                <Outlet />
            </div>
        </div>
    );
}
