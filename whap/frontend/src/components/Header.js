import React, { useContext } from 'react';
import { Link as RouterLink, useLocation } from 'react-router-dom';
import {
    Box,
    Typography,
    Button,
    IconButton,
    Tooltip
} from '@mui/material';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import DashboardIcon from '@mui/icons-material/Dashboard';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import MenuIcon from '@mui/icons-material/Menu';
import LogoutIcon from '@mui/icons-material/Logout';
import { AuthContext } from '../contexts/AuthContext';

function Header({ title, onMenuClick }) {
    const { username, isAdmin, logout } = useContext(AuthContext);
    const location = useLocation();

    // Check the current path to disable the corresponding button
    const isDashboard = location.pathname === '/user';
    const isDocs = location.pathname === '/docs';
    const isAdminPage = location.pathname.startsWith('/admin');

    return (
        <Box sx={{
            display: 'flex',
            // Mobile: Column reverse puts the second child (Buttons) on top of the first child (Title)
            // Desktop: Standard Row
            flexDirection: { xs: 'column-reverse', md: 'row' },
            justifyContent: 'space-between',
            alignItems: 'center',
            mb: 4,
            pb: 2,
            borderBottom: '1px solid #e0e0e0',
            gap: 2
        }}>
            {/* Title Section (Bottom on Mobile, Left on Desktop) */}
            <Box sx={{
                display: 'flex',
                alignItems: 'center',
                width: { xs: '100%', md: 'auto' } // Full width on mobile for alignment
            }}>
                {onMenuClick && (
                    <IconButton
                        color="inherit"
                        aria-label="open drawer"
                        edge="start"
                        onClick={onMenuClick}
                        sx={{ mr: 2, display: { md: 'none' } }}
                    >
                        <MenuIcon />
                    </IconButton>
                )}

                <Typography variant="h4" component="h1" sx={{ fontWeight: 500, whiteSpace: 'nowrap' }}>
                    {title}
                </Typography>
            </Box>

            {username && (
                <Box sx={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: { xs: 'flex-end', md: 'flex-end' }, // Align right
                    width: { xs: '100%', md: 'auto' }, // Full width on mobile
                    flexWrap: 'wrap', // Allow buttons to wrap to next line if screen is tiny
                    gap: 1
                }}>
                    <Typography variant="body1" sx={{ mr: 2, display: { xs: 'none', md: 'block' } }}>
                        Welcome, <strong data-testid="header-username">{username}</strong>!
                    </Typography>

                    {/* Docs Button - Hidden if already on /docs */}
                    {!isDocs && (
                        <Tooltip title="Documentation">
                            <Button
                                component={RouterLink}
                                to="/docs"
                                variant="outlined"
                                color="info"
                                size="small"
                                startIcon={<HelpOutlineIcon />}
                            >
                                Docs
                            </Button>
                        </Tooltip>
                    )}

                    {/* Navigation Buttons */}
                    {isAdmin && !isAdminPage && (
                        <Button
                            component={RouterLink}
                            to="/admin"
                            variant="contained"
                            color="secondary"
                            size="small"
                            startIcon={<AdminPanelSettingsIcon />}
                        >
                            Admin Panel
                        </Button>
                    )}

                    {!isDashboard && (
                        <Button
                            component={RouterLink}
                            to="/user"
                            variant="outlined"
                            size="small"
                            startIcon={<DashboardIcon />}
                        >
                            User Panel
                        </Button>
                    )}

                    <Tooltip title="Logout">
                        <IconButton onClick={logout} color="default" size="small" sx={{ ml: 1 }}
                                    aria-label="Logout" data-testid="header-logout">
                            <LogoutIcon />
                        </IconButton>
                    </Tooltip>
                </Box>
            )}
        </Box>
    );
}

export default Header;