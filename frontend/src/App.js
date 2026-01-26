import {BrowserRouter, Route, Routes} from "react-router-dom";
import Index from "./pages";
import Testimonials from "./pages/testimonials";
import {ToastProvider} from "./components/ToastContext";
import AdminLayout from "./components/AdminLayout";
import HeaderMenu from "./pages/headerMenu";
import LoginPage from "./pages/loginPage";
import RegisterPage from "./pages/registerPage";
import UsersPage from "./pages/usersPage";
import {AuthProvider} from "./hooks/authContext";
import PrivateRoute from "./components/PrivateRoute";
import AdminPage from "./pages/adminPage";

export default function App() {
    return (
        <BrowserRouter basename="/admin">
            <AuthProvider>
                <ToastProvider>
                    <Routes>
                        <Route path="/login" element={<LoginPage/>}/>
                        <Route path="/register" element={<RegisterPage/>}/>

                        <Route
                            path="/"
                            element={
                                <PrivateRoute>
                                    <AdminLayout/>
                                </PrivateRoute>
                            }
                        >
                            <Route index element={<Index/>}/>
                            <Route path="testimonials" element={<Testimonials/>}/>
                            <Route path="header-menu" element={<HeaderMenu/>}/>

                            <Route
                                path="admin"
                                element={
                                    <PrivateRoute allowedRoles={["admin", "moderator"]}>
                                        <AdminPage/>
                                    </PrivateRoute>
                                }
                            />

                            <Route
                                path="users"
                                element={
                                    <PrivateRoute allowedRoles={["admin"]}>
                                        <UsersPage/>
                                    </PrivateRoute>
                                }
                            />
                        </Route>
                    </Routes>
                </ToastProvider>
            </AuthProvider>
        </BrowserRouter>
    );
}
