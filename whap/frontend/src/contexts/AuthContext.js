import React, { createContext, useState, useEffect, useCallback } from 'react';
import api from '../services/api';
import { CircularProgress, Box } from '@mui/material';

export const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
    // Store more detailed user info
    const [user, setUser] = useState(null); // Now stores { id, username, user_type, is_admin }
    const [loading, setLoading] = useState(true);

    const checkSession = useCallback(async () => {
        // setLoading(true); // Avoid brief flicker if already logged in
        try {
            const response = await api.get('/auth/session');
            if (response.data && response.data.isLoggedIn && response.data.user) {
                setUser(response.data.user); // Store the whole user object from backend
            } else {
                setUser(null);
            }
        } catch (error) {
            console.error('Session check failed:', error);
            setUser(null);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        checkSession();
    }, [checkSession]);

    const login = async (username, password) => {
        try {
            const response = await api.post('/auth/login', { username, password });
            if (response.data && response.data.user) {
                setUser(response.data.user); // Store the user object from backend
                return true;
            }
            return false;
        } catch (error) {
            console.error('Login failed:', error);
            throw error;
        }
    };

    const logout = async () => {
        try {
            await api.post('/auth/logout');
        } catch (error) {
            console.error('Logout failed:', error);
        } finally {
            setUser(null);
            setLoading(false);
        }
    };

    // Expose specific flags for convenience
    const isAuthenticated = !!user;
    const isAdmin = user ? user.is_admin : false;
    const userType = user ? user.user_type : null;
    const username = user ? user.username : null;

    const authContextValue = {
        user, // Full user object { id, username, user_type, is_admin }
        isAuthenticated,
        isAdmin, // Convenience flag
        userType, // Convenience flag
        username, // Convenience flag
        loading,
        login,
        logout,
        checkSession,
    };

    if (loading) {
        return (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
                <CircularProgress />
            </Box>
        );
    }

    return (
        <AuthContext.Provider value={authContextValue}>
            {children}
        </AuthContext.Provider>
    );
};