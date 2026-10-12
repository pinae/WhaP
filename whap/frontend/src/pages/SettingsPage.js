import React from 'react';
import { Box, Container } from '@mui/material';
import Header from '../components/Header';
import NotificationSettings from '../components/NotificationSettings';

function SettingsPage() {
    return (
        <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
            <Header title="Settings" />
            <Box sx={{ maxWidth: 860, mx: 'auto' }}>
                <NotificationSettings />
            </Box>
        </Container>
    );
}

export default SettingsPage;
