import React, {useState, useEffect} from 'react';
import {
    Box,
    Container,
    Typography,
    CircularProgress,
    Alert
} from '@mui/material';
import api from '../services/api';
import ServerStats from './ServerStats';

function ClusterStatistics() {
    const [servers, setServers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    useEffect(() => {
        const fetchServers = async () => {
            try {
                // We reuse the existing endpoint to get the list of servers to display
                const response = await api.get('/api/servers');
                // Sort servers by hostname for consistent display
                const sortedServers = (response.data || []).sort((a, b) =>
                    a.hostname.localeCompare(b.hostname)
                );
                setServers(sortedServers);
            } catch (err) {
                console.error("Failed to load server list:", err);
                setError("Failed to load cluster server list. Please verify backend connection.");
            } finally {
                setLoading(false);
            }
        };

        fetchServers();
    }, []);

    if (loading) {
        return (
            <Box sx={{display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh'}}>
                <CircularProgress/>
            </Box>
        );
    }

    if (error) {
        return (
            <Container maxWidth="lg" sx={{mt: 4}}>
                <Alert severity="error">{error}</Alert>
            </Container>
        );
    }

    if (servers.length === 0) {
        return (
            <Container maxWidth="lg" sx={{mt: 4}}>
                <Alert severity="info">No compute servers are currently configured.</Alert>
            </Container>
        );
    }

    return (
        <Box>
            {servers.map(server => (
                <ServerStats key={server.id} server={server}/>
            ))}
        </Box>
    );
}

export default ClusterStatistics;