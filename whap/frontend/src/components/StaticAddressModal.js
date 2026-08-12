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
    FormGroup,
    FormControlLabel,
    Checkbox,
    Typography,
    Grid,
    Select,
    MenuItem,
    InputLabel,
    FormControl,
    FormHelperText
} from '@mui/material';
import api from '../services/api';

// addressToEdit will be null for Add mode, or object for Edit mode
// allServers should be [{id: 1, hostname: '...'}, ...]
function StaticAddressModal({open, onClose, onSave, addressToEdit, allServers = [], allNetworks = []}) {
    const [formData, setFormData] = useState({
        ip_address: '',
        mac_address: '',
        comment: '',
        network_id: ''
    });
    const [selectedServerIds, setSelectedServerIds] = useState(new Set()); // Use a Set for efficient add/delete
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const isEditMode = Boolean(addressToEdit);

    // Effect to populate form when editing
    useEffect(() => {
        if (isEditMode && addressToEdit) {
            setFormData({
                ip_address: addressToEdit.ip_address || '',
                mac_address: addressToEdit.mac_address || '',
                comment: addressToEdit.comment || '',
                network_id: addressToEdit.network_id || '',
            });
            // Initialize selected servers based on addressToEdit.available_server_ids
            setSelectedServerIds(new Set(addressToEdit.available_server_ids || []));
        } else {
            // Reset form for Add mode
            setFormData({ip_address: '', mac_address: '', comment: '', network_id: ''});
            setSelectedServerIds(new Set());
        }
        // Reset error when dialog opens or mode changes
        setError('');
    }, [open, addressToEdit, isEditMode]);

    const handleClose = () => {
        if (loading) return;
        onClose();
    };

    const handleServerCheckboxChange = (event) => {
        const serverId = parseInt(event.target.value, 10);
        const isChecked = event.target.checked;
        setSelectedServerIds(prev => {
            const newSet = new Set(prev);
            if (isChecked) {
                newSet.add(serverId);
            } else {
                newSet.delete(serverId);
            }
            return newSet;
        });
    };

    const handleSubmit = async (event) => {
        event.preventDefault();
        const {ip_address, mac_address, comment, network_id} = formData;
        const trimmedIp = ip_address.trim();
        const trimmedMac = mac_address.trim();

        // Basic client-side validation (backend does more thorough)
        if (!trimmedIp || !trimmedMac || !network_id) {
            setError('IP Address, MAC Address, and a Network selection are required.');
            return;
        }
        // Basic format checks
        if (!/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(trimmedIp)) { // Very basic IPv4 check
            setError('Invalid IP Address format.');
            return;
        }
        if (!/^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$/.test(trimmedMac)) {
            setError('Invalid MAC Address format (use XX:XX:XX:XX:XX:XX).');
            return;
        }

        setLoading(true);
        setError('');

        try {
            const payload = {
                ip_address: trimmedIp,
                mac_address: trimmedMac,
                comment: comment.trim(),
                network_id: network_id,
                available_server_ids: Array.from(selectedServerIds), // Convert Set to Array
            };

            if (isEditMode) {
                await api.put(`/api/admin/static_addresses/${addressToEdit.id}`, payload);
            } else {
                await api.post('/api/admin/static_addresses', payload);
            }

            onSave(); // Callback to trigger refresh in parent
            handleClose(); // Close modal on success

        } catch (err) {
            console.error("Failed to save static address:", err);
            setError(err.response?.data?.message || `Failed to ${isEditMode ? 'update' : 'create'} address.`);
        } finally {
            setLoading(false);
        }
    };

    return (
        <Dialog open={open} onClose={handleClose} aria-labelledby="address-dialog-title" maxWidth="sm" fullWidth>
            <DialogTitle
                id="address-dialog-title">{isEditMode ? 'Edit Static Address' : 'Add New Static Address'}</DialogTitle>
            <Box component="form" onSubmit={handleSubmit}>
                <DialogContent>
                    {error && <Alert severity="error" sx={{mb: 2}}>{error}</Alert>}
                    <Grid container spacing={2}> {/* Use Grid for layout */}
                        <Grid item xs={12} sm={8}>
                            <TextField autoFocus margin="dense" id="ip_address" label="IP Address" type="text" fullWidth
                                       variant="outlined" value={formData.ip_address}
                                       onChange={(e) => setFormData(f => ({...f, ip_address: e.target.value}))}
                                       disabled={loading} required/>
                        </Grid>
                        <Grid item xs={12} sm={7}>
                            <TextField margin="dense" id="mac_address" label="MAC Address"
                                       placeholder="XX:XX:XX:XX:XX:XX" type="text" fullWidth variant="outlined"
                                       value={formData.mac_address}
                                       onChange={(e) => setFormData(f => ({...f, mac_address: e.target.value}))}
                                       disabled={loading} required/>
                        </Grid>
                        <FormControl fullWidth required margin="dense" sx={{mb: 2}}
                                     error={!formData.network_id && !!error}>
                            <InputLabel id="network-select-label">Network</InputLabel>
                            <Select
                                labelId="network-select-label"
                                id="network_id"
                                name="network_id"
                                value={formData.network_id}
                                label="Network"
                                onChange={(e) => setFormData(f => ({...f, network_id: e.target.value}))}
                                disabled={loading}
                            >
                                <MenuItem value="" disabled><em>Select a network</em></MenuItem>
                                {allNetworks.map((net) => (
                                    <MenuItem key={net.id}
                                              value={net.id}>{net.name} ({net.base_ip}/{net.prefix_size})</MenuItem>
                                ))}
                            </Select>
                            {allNetworks.length === 0 &&
                                <FormHelperText>No networks configured. Add one first.</FormHelperText>}
                        </FormControl>
                        <Grid item xs={12}>
                            <TextField margin="dense" id="comment" label="Comment (Optional)" type="text" fullWidth
                                       variant="outlined" value={formData.comment}
                                       onChange={(e) => setFormData(f => ({...f, comment: e.target.value}))}
                                       disabled={loading}/>
                        </Grid>
                    </Grid>
                    <Typography variant="subtitle1" sx={{mt: 2, mb: 1}}>Available On Servers:</Typography>
                    {allServers.length > 0 ? (
                        <FormGroup sx={{
                            maxHeight: '200px',
                            overflowY: 'auto',
                            border: '1px solid #ccc',
                            borderRadius: 1,
                            p: 1
                        }}>
                            <Grid container spacing={0}>
                                {allServers.sort((a, b) => a.hostname.localeCompare(b.hostname)).map((server) => (
                                    <Grid item xs={6} sm={4} key={server.id}> {/* Adjust grid size as needed */}
                                        <FormControlLabel
                                            control={
                                                <Checkbox
                                                    checked={selectedServerIds.has(server.id)}
                                                    onChange={handleServerCheckboxChange}
                                                    value={server.id}
                                                    disabled={loading}
                                                    size="small"
                                                />
                                            }
                                            label={<Typography variant="body2">{server.hostname}</Typography>}
                                        />
                                    </Grid>
                                ))}
                            </Grid>
                        </FormGroup>
                    ) : (
                        <Typography variant="body2" color="textSecondary">No compute servers configured.</Typography>
                    )}

                </DialogContent>
                <DialogActions sx={{position: 'relative', pr: 3, pb: 2}}>
                    <Button onClick={handleClose} disabled={loading} color="secondary"> Cancel </Button>
                    <Button type="submit" disabled={loading} variant="contained" color="primary">
                        {isEditMode ? 'Save Changes' : 'Add Address'}
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

export default StaticAddressModal;