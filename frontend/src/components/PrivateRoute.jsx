import { Navigate } from "react-router-dom";
import { useAuth } from "../hooks/authContext";

export default function PrivateRoute({ children, allowedRoles }) {
    const { user, accessToken, loading } = useAuth();

    if (loading) {
        return null;
    }

    if (!accessToken || !user) {
        return <Navigate to="/login" replace />;
    }

    if (allowedRoles && !allowedRoles.includes(user.role)) {
        return <Navigate to="/" replace />;
    }

    return children;
}
