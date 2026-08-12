import React, {useState, useEffect} from 'react';
import {
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogContentText,
    DialogTitle,
    Grid,
    TextField,
    CircularProgress,
    Alert,
    Box
} from '@mui/material';
import api from '../services/api';

// serverToEdit will be null for Add mode, or {id, hostname} for Edit mode
function ComputeServerModal({open, onClose, onSave, serverToEdit}) {
    const [hostname, setHostname] = useState('');
    const [sshPort, setSshPort] = useState('22');
    const [gpuCount, setGpuCount] = useState('1');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const isEditMode = Boolean(serverToEdit);

    // Effect to populate form when editing
    useEffect(() => {
        if (isEditMode && serverToEdit) {
            setHostname(serverToEdit.hostname || '');
            setSshPort(serverToEdit.ssh_port || '22');
            setGpuCount(serverToEdit.gpu_count !== undefined ? serverToEdit.gpu_count : '1');
        } else {
            // Reset form for Add mode or when dialog closes/prop changes
            setHostname('');
            setSshPort('22');
            setGpuCount('1');
        }
        // Reset error when dialog opens or mode changes
        setError('');
    }, [open, serverToEdit, isEditMode]);

    const handleClose = () => {
        if (loading) return;
        // No need to reset state here, useEffect handles it based on `open`
        onClose();
    };

    const handleSubmit = async (event) => {
        event.preventDefault();
        const trimmedHostname = hostname.trim();
        if (!trimmedHostname) {
            setError('Hostname cannot be empty.');
            return;
        }
        // Basic validation (optional, backend does more)
        if (!/^[a-zA-Z0-9.-]+$/.test(trimmedHostname)) {
            setError('Invalid hostname format. Use letters, numbers, dots, hyphens.');
            return;
        }

        const portNumber = parseInt(sshPort, 10);
        if (isNaN(portNumber) || portNumber < 1 || portNumber > 65535) {
            setError('SSH Port must be a number between 1 and 65535.');
            return;
        }

        const gpuCountNumber = parseInt(gpuCount, 10);
        if (isNaN(gpuCountNumber) || gpuCountNumber < 0) {
            setError('GPU Count must be a non-negative number.');
            return;
        }

        setLoading(true);
        setError('');

        try {
            let response;
            const payload = {
                hostname: trimmedHostname,
                ssh_port: portNumber,
                gpu_count: gpuCountNumber
            };

            if (isEditMode) {
                // Update existing server
                response = await api.put(`/api/admin/servers/${serverToEdit.id}`, payload);
            } else {
                // Create new server
                response = await api.post('/api/admin/servers', payload);
            }

            onSave(response.data); // Callback to trigger refresh in parent
            handleClose(); // Close modal on success

        } catch (err) {
            console.error("Failed to save server:", err);
            setError(err.response?.data?.message || `Failed to ${isEditMode ? 'update' : 'create'} server.`);
        } finally {
            setLoading(false);
        }
    };

    return (
        <Dialog open={open} onClose={handleClose} aria-labelledby="server-dialog-title">
            <DialogTitle
                id="server-dialog-title">{isEditMode ? 'Edit Compute Server' : 'Add New Compute Server'}</DialogTitle>
            <Box component="form" onSubmit={handleSubmit}>
                <DialogContent>
                    <DialogContentText sx={{mb: 2}}>
                        Enter the hostname or IP address of the compute server.
                    </DialogContentText>
                    {error && <Alert severity="error" sx={{mb: 2}}>{error}</Alert>}
                    <TextField
                        autoFocus
                        margin="dense"
                        id="hostname"
                        label="Hostname / IP Address"
                        type="text"
                        fullWidth
                        variant="outlined"
                        value={hostname}
                        onChange={(e) => setHostname(e.target.value)}
                        disabled={loading}
                        required
                    />
                    <Grid container spacing={2}>
                        <Grid item xs={6}>
                            <TextField
                                margin="dense"
                                id="ssh_port"
                                label="SSH Port"
                                type="number"
                                fullWidth
                                variant="outlined"
                                value={sshPort}
                                onChange={(e) => setSshPort(e.target.value)}
                                disabled={loading}
                                required
                                slotProps={{input: {min: 1, max: 65535}, htmlInput: {min: 1, max: 65535}}}
                            />
                        </Grid>
                        <Grid item xs={6}>
                            <TextField
                                margin="dense"
                                id="gpu_count"
                                label="GPU Count"
                                type="number"
                                fullWidth
                                variant="outlined"
                                value={gpuCount}
                                onChange={(e) => setGpuCount(e.target.value)}
                                disabled={loading}
                                required
                                slotProps={{input: {min: 0, max: 8}, htmlInput: {min: 0, max: 8}}}/>
                        </Grid>
                    </Grid>
                </DialogContent>
                <DialogActions sx={{position: 'relative', pr: 3, pb: 2}}>
                    <Button onClick={handleClose} disabled={loading} color="secondary">
                        Cancel
                    </Button>
                    <Button type="submit" disabled={loading} variant="contained" color="primary">
                        {isEditMode ? 'Save Changes' : 'Add Server'}
                        {loading && (
                            <CircularProgress
                                size={24}
                                sx={{
                                    position: 'absolute',
                                    top: '50%',
                                    left: '50%',
                                    marginTop: '-12px',
                                    marginLeft: '-12px',
                                }}
                            />
                        )}
                    </Button>
                </DialogActions>
            </Box>
        </Dialog>
    );
}

export default ComputeServerModal;