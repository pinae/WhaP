import React, {useState, useEffect} from 'react';
import {
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    TextField,
    CircularProgress,
    Alert,
    Box,
    Grid
} from '@mui/material';
import api from '../services/api';

function NetworkModal({open, onClose, onSave, networkToEdit}) {
    const [formData, setFormData] = useState({name: '', base_ip: '', prefix_size: '', gateway: ''});
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const isEditMode = Boolean(networkToEdit);

    useEffect(() => {
        if (isEditMode && networkToEdit) {
            setFormData({
                name: networkToEdit.name || '',
                base_ip: networkToEdit.base_ip || '',
                prefix_size: networkToEdit.prefix_size || '',
                gateway: networkToEdit.gateway || '',
            });
        } else {
            setFormData({name: '', base_ip: '', prefix_size: '', gateway: ''});
        }
        setError('');
    }, [open, networkToEdit, isEditMode]);

    const handleClose = () => {
        if (loading) return;
        onClose();
    };

    const handleSubmit = async (event) => {
        event.preventDefault();
        setLoading(true);
        setError('');
        try {
            const payload = {
                name: formData.name.trim(),
                base_ip: formData.base_ip.trim(),
                prefix_size: formData.prefix_size.toString().trim(),
                gateway: formData.gateway.trim(),
            };
            if (isEditMode) {
                await api.put(`/api/admin/networks/${networkToEdit.id}`, payload);
            } else {
                await api.post('/api/admin/networks', payload);
            }
            onSave(); // Trigger refresh in parent
            handleClose();
        } catch (err) {
            console.error("Failed to save network:", err);
            setError(err.response?.data?.message || `Failed to ${isEditMode ? 'update' : 'create'} network.`);
        } finally {
            setLoading(false);
        }
    };

    return (
        <Dialog open={open} onClose={handleClose} aria-labelledby="network-dialog-title" maxWidth="sm" fullWidth>
            <DialogTitle id="network-dialog-title">{isEditMode ? 'Edit Network' : 'Add New Network'}</DialogTitle>
            <Box component="form" onSubmit={handleSubmit}>
                <DialogContent>
                    {error && <Alert severity="error" sx={{mb: 2}}>{error}</Alert>}
                    <TextField autoFocus margin="dense" id="name" label="Network Name" type="text" fullWidth
                               variant="outlined" value={formData.name}
                               onChange={(e) => setFormData(f => ({...f, name: e.target.value}))} disabled={loading}
                               required sx={{mb: 2}}/>
                    <Grid container spacing={2}>
                        <Grid item xs={12} sm={8}>
                            <TextField margin="dense" id="base_ip" label="Subnet Base IP"
                                       placeholder="e.g., 192.168.10.0" type="text" fullWidth variant="outlined"
                                       value={formData.base_ip}
                                       onChange={(e) => setFormData(f => ({...f, base_ip: e.target.value}))}
                                       disabled={loading} required/>
                        </Grid>
                        <Grid item xs={12} sm={4}>
                            <TextField margin="dense" id="prefix_size" label="Subnet Size" placeholder="e.g., 24"
                                       type="number" fullWidth variant="outlined" value={formData.prefix_size}
                                       onChange={(e) => setFormData(f => ({...f, prefix_size: e.target.value}))}
                                       disabled={loading} required inputProps={{min: 1, max: 32}}/>
                        </Grid>
                    </Grid>
                    <TextField margin="dense" id="gateway" label="Gateway IP" type="text" fullWidth variant="outlined"
                               value={formData.gateway}
                               onChange={(e) => setFormData(f => ({...f, gateway: e.target.value}))} disabled={loading}
                               required sx={{mt: 1}}/>
                </DialogContent>
                <DialogActions sx={{position: 'relative', pr: 3, pb: 2}}>
                    <Button onClick={handleClose} disabled={loading} color="secondary">Cancel</Button>
                    <Button type="submit" disabled={loading} variant="contained" color="primary">
                        {isEditMode ? 'Save Changes' : 'Add Network'}
                        {loading && <CircularProgress size={24} sx={{
                            position: 'absolute',
                            top: '50%',
                            left: '50%',
                            marginTop: '-12px',
                            marginLeft: '-12px'
                        }}/>}
                    </Button>
                </DialogActions>
            </Box>
        </Dialog>
    );
}

export default NetworkModal;