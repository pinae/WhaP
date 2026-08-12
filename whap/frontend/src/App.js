import React, { useContext } from 'react'; // Added useContext
import { BrowserRouter as Router, Routes, Route, Navigate, Outlet, useLocation } from 'react-router-dom';
import { Box, CircularProgress } from '@mui/material'; // For loading indicators
import { ThemeProvider } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import { AuthProvider, AuthContext } from './contexts/AuthContext';
import theme from './theme';
import LoginPage from './pages/LoginPage';
import UserPage from './pages/UserPage';
import AdminPage from './pages/AdminPage'; // Import AdminPage
import DocumentationPage from './pages/DocumentationPage';

// Wrapper for protected routes (standard users and admins)
function ProtectedRoute() {
  const { isAuthenticated, loading } = useContext(AuthContext); // Use lowercase here
  const location = useLocation();

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return isAuthenticated ? (
    <Outlet />
  ) : (
    <Navigate to="/login" state={{ from: location }} replace />
  );
}

// Wrapper specifically for admin routes
function AdminRoute() {
  const { isAuthenticated, isAdmin, loading } = useContext(AuthContext); // Use lowercase here
  const location = useLocation();

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  if (!isAuthenticated) {
    // Redirect to login if not authenticated at all
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return isAdmin ? (
    <Outlet /> // Render admin child component
  ) : (
    // Redirect to dashboard (or show forbidden message) if authenticated but not admin
    <Navigate to="/user" state={{ message: "Access Denied: Admin privileges required." }} replace />
  );
}


function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <AuthProvider>
        <Router>
          <Routes>
            {/* Public Route */}
            <Route path="/login" element={<LoginPage />} />

            {/* Protected Routes (Standard Users + Admins) */}
            <Route element={<ProtectedRoute />}>
              <Route path="/user" element={<UserPage />} />
              <Route path="/docs" element={<DocumentationPage />} />
              {/* Add other standard protected routes here */}
            </Route>

            {/* Admin Only Routes */}
            <Route element={<AdminRoute />}>
              <Route path="/admin" element={<AdminPage />} />
              {/* Add other admin-only routes here */}
            </Route>

            {/* Redirect base path */}
            {/* Decide where '/' should go - login if not logged in, dashboard otherwise? */}
            <Route
              path="/"
              element={
                <RequireAuthRedirect>
                  <Navigate to="/user" replace />
                </RequireAuthRedirect>
              }
            />

            {/* Fallback for unknown routes */}
            <Route path="*" element={<Navigate to="/" replace />} />

          </Routes>
        </Router>
      </AuthProvider>
    </ThemeProvider>
  );
}

// Helper component to redirect '/' based on auth status
function RequireAuthRedirect({ children }) {
  const { isAuthenticated, loading } = useContext(AuthContext); // Use lowercase here
  if (loading) {
    return <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}><CircularProgress /></Box>;
  }
  return isAuthenticated ? children : <Navigate to="/login" replace />;
}


export default App;