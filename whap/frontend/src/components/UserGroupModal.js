import React, { useState, useEffect, useMemo } from 'react';
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
    Grid,
    Paper,
    Checkbox,
    Typography,
    FormGroup,
    FormControl,
    FormControlLabel,
    InputLabel,
    Select,
    MenuItem,
    List,
    ListItem,
    ListItemText,
    IconButton,
} from '@mui/material';
import AddCircleOutlineIcon from '@mui/icons-material/AddCircleOutline';
import RemoveCircleOutlineIcon from '@mui/icons-material/RemoveCircleOutline';
import api from '../services/api';
import UserSearchAndManage from './UserSearchAndManage';
import ImageWhitelistSelector from "./ImageWhitelistSelector";

function UserGroupModal({ open, onClose, onGroupSaved, groupToEdit, userPermissions, allServers, allImages }) {
    const isEditMode = Boolean(groupToEdit);
    // Form State
    const [name, setName] = useState('');
    const [selectedImages, setSelectedImages] = useState([]);
    const [selectedServerIds, setSelectedServerIds] = useState(new Set());
    const [gpuAccessRules, setGpuAccessRules] = useState({});
    const [cpuAccessRules, setCpuAccessRules] = useState({});
    const [members, setMembers] = useState([]);
    // UI State
    const [newGpuRule, setNewGpuRule] = useState({ serverId: '', gpus: '' });
    const [newCpuRule, setNewCpuRule] = useState({ serverId: '', cpuLimit: '' });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    useEffect(() => {
        if (open) {
            if (isEditMode && groupToEdit) {
                setName(groupToEdit.name || '');
                setSelectedImages(groupToEdit.image_whitelist || []);
                setSelectedServerIds(new Set(groupToEdit.accessible_server_ids || []));
                setMembers(groupToEdit.members || []);

                const rules = groupToEdit.gpu_access_rules || [];
                if (Array.isArray(rules)) {
                    const rulesDict = rules.reduce((acc, rule) => {
                        acc[rule.compute_server_id] = rule.allowed_gpus;
                        return acc;
                    }, {});
                    setGpuAccessRules(rulesDict);
                } else {
                    // If it's already an object/dictionary, use it directly
                    setGpuAccessRules(rules);
                }

                setCpuAccessRules(groupToEdit.cpu_access_rules || {});


            } else {
                // Reset state for "create" mode
                setName('');
                setSelectedImages([]);
                setSelectedServerIds(new Set());
                setGpuAccessRules({});
                setCpuAccessRules({});
                setMembers([]);
            }
            setNewGpuRule({ serverId: '', gpus: '' });
            setNewCpuRule({ serverId: '', cpuLimit: '' });
            setError('');
        }
    }, [open, groupToEdit, isEditMode]);

    const availableServers = useMemo(() => {
        if (!userPermissions) return [];
        return userPermissions.accessible_server_ids.includes('*')
            ? allServers
            : allServers.filter(s => userPermissions.accessible_server_ids.includes(s.id));
    }, [userPermissions, allServers]);

    const handleServerCheckboxChange = (event) => {
        const serverId = parseInt(event.target.value, 10);
        setSelectedServerIds(prev => {
            const newSet = new Set(prev);
            if (event.target.checked) newSet.add(serverId);
            else newSet.delete(serverId);
            return newSet;
        });
    };

    const handleAddGpuRule = () => {
        if (!newGpuRule.serverId || !newGpuRule.gpus.trim()) return;
        if (newGpuRule.serverId in gpuAccessRules) {
            setError(`A GPU rule already exists for this server. Please remove it first.`);
            return;
        }
        setGpuAccessRules(prev => ({
            ...prev,
            [newGpuRule.serverId]: newGpuRule.gpus.trim(),
        }));
        setNewGpuRule({ serverId: '', gpus: '' });
        setError('');
    };

    const handleRemoveGpuRule = (serverIdToRemove) => {
        setGpuAccessRules(prev => {
            const newRules = { ...prev };
            delete newRules[serverIdToRemove];
            return newRules;
        });
    };

    const handleAddCpuRule = () => {
        if (!newCpuRule.serverId) return;
        // Allow empty string for "unlimited" or handle explicitly
        // If user types "unlimited", we send "unlimited".
        // If user leaves blank, maybe warn?
        // UI should guide.
        if (!newCpuRule.cpuLimit) return;

        if (newCpuRule.serverId in cpuAccessRules) {
            setError(`A CPU rule already exists for this server. Please remove it first.`);
            return;
        }
        setCpuAccessRules(prev => ({
            ...prev,
            [newCpuRule.serverId]: newCpuRule.cpuLimit.trim(),
        }));
        setNewCpuRule({ serverId: '', cpuLimit: '' });
        setError('');
    };

    const handleRemoveCpuRule = (serverIdToRemove) => {
        setCpuAccessRules(prev => {
            const newRules = { ...prev };
            delete newRules[serverIdToRemove];
            return newRules;
        });
    };

    const handleSubmit = async (event) => {
        event.preventDefault();
        setLoading(true);
        setError('');
        try {
            const payload = {
                name: name.trim(),
                image_whitelist: selectedImages,
                accessible_server_ids: Array.from(selectedServerIds),
                gpu_access_rules: gpuAccessRules,
                cpu_access_rules: cpuAccessRules,
                members: members,
            };

            let response;
            if (isEditMode) {
                response = await api.put(`/api/groups/${groupToEdit.id}`, payload);
            } else {
                response = await api.post('/api/groups', payload);
            }
            onGroupSaved(response.data);
            onClose();
        } catch (err) {
            console.error("Failed to save group:", err);
            setError(err.response?.data?.message || 'Failed to save group.');
        } finally {
            setLoading(false);
        }
    };

    return (
        <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
            <DialogTitle>{isEditMode ? `Edit Group: ${groupToEdit?.name}` : 'Create New Group'}</DialogTitle>
            <Box component="form" onSubmit={handleSubmit}>
                <DialogContent>
                    {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
                    <TextField autoFocus margin="dense" id="name" label="Group Name" type="text" fullWidth variant="outlined" value={name} onChange={(e) => setName(e.target.value)} disabled={loading} required />

                    <Typography variant="subtitle1" sx={{ mt: 2, mb: 1 }}>Permissions</Typography>
                    <Paper variant="outlined" sx={{ p: 2 }}>
                        <ImageWhitelistSelector
                            allImages={allImages}
                            selectedImages={selectedImages}
                            onSelectionChange={setSelectedImages}
                            disabled={loading}
                        />

                        <Typography variant="subtitle2" sx={{ mt: 2, mb: 1 }}>Grant Server Access:</Typography>
                        <FormGroup sx={{ maxHeight: 150, overflowY: 'auto', border: '1px solid #ccc', borderRadius: 1, p: 1, mb: 2 }}>
                            {availableServers.length > 0 ? (
                                <Grid container>
                                    {availableServers.map((server) => (
                                        <Grid item xs={6} sm={4} key={server.id}>
                                            <FormControlLabel control={<Checkbox checked={selectedServerIds.has(server.id)} onChange={handleServerCheckboxChange} value={server.id} disabled={loading} size="small" />} label={<Typography variant="body2">{server.hostname}</Typography>} />
                                        </Grid>
                                    ))}
                                </Grid>
                            ) : (<Typography sx={{ p: 2, textAlign: 'center', color: 'text.secondary' }}>You have no server permissions to grant.</Typography>)}
                        </FormGroup>

                        <Typography variant="subtitle2" sx={{ mt: 2, mb: 1 }}>Grant GPU Access (per Server):</Typography>
                        <Grid container spacing={2} alignItems="center">
                            <Grid item xs={12} sm={5}><FormControl fullWidth size="small"><InputLabel>Server</InputLabel><Select label="Server" value={newGpuRule.serverId} onChange={(e) => setNewGpuRule(prev => ({ ...prev, serverId: e.target.value }))}>{availableServers.map(s => <MenuItem key={s.id} value={s.id}>{s.hostname}</MenuItem>)}</Select></FormControl></Grid>
                            <Grid item xs={12} sm={5}><TextField fullWidth size="small" label="Allowed GPUs" placeholder="e.g., 0,1 or *" value={newGpuRule.gpus} onChange={(e) => setNewGpuRule(prev => ({ ...prev, gpus: e.target.value }))} /></Grid>
                            <Grid item xs={12} sm={2}><Button fullWidth variant="outlined" onClick={handleAddGpuRule} startIcon={<AddCircleOutlineIcon />}>Add</Button></Grid>
                        </Grid>
                        {Object.keys(gpuAccessRules).length > 0 &&
                            <List dense sx={{ maxHeight: 150, overflow: 'auto', mt: 1 }}>
                                {Object.entries(gpuAccessRules).map(([serverId, allowedGpus]) => (
                                    <ListItem key={serverId} secondaryAction={<IconButton edge="end" onClick={() => handleRemoveGpuRule(serverId)}><RemoveCircleOutlineIcon color="error" /></IconButton>}>
                                        <ListItemText primary={`Server: ${allServers.find(s => s.id == serverId)?.hostname || 'Unknown'}`} secondary={`GPUs: ${allowedGpus}`} />
                                    </ListItem>
                                ))}
                            </List>
                        }
                        <Typography variant="subtitle2" sx={{ mt: 2, mb: 1 }}>Grant CPU Access (per Server):</Typography>
                        <Grid container spacing={2} alignItems="center">
                            <Grid item xs={12} sm={5}><FormControl fullWidth size="small"><InputLabel>Server</InputLabel><Select label="Server" value={newCpuRule.serverId} onChange={(e) => setNewCpuRule(prev => ({ ...prev, serverId: e.target.value }))}>{availableServers.map(s => <MenuItem key={s.id} value={s.id}>{s.hostname}</MenuItem>)}</Select></FormControl></Grid>
                            <Grid item xs={12} sm={5}><TextField fullWidth size="small" label="CPU Limit" placeholder="e.g., 4 or 'unlimited'" value={newCpuRule.cpuLimit} onChange={(e) => setNewCpuRule(prev => ({ ...prev, cpuLimit: e.target.value }))} /></Grid>
                            <Grid item xs={12} sm={2}><Button fullWidth variant="outlined" onClick={handleAddCpuRule} startIcon={<AddCircleOutlineIcon />}>Add</Button></Grid>
                        </Grid>
                        {Object.keys(cpuAccessRules).length > 0 &&
                            <List dense sx={{ maxHeight: 150, overflow: 'auto', mt: 1 }}>
                                {Object.entries(cpuAccessRules).map(([serverId, limit]) => (
                                    <ListItem key={serverId} secondaryAction={<IconButton edge="end" onClick={() => handleRemoveCpuRule(serverId)}><RemoveCircleOutlineIcon color="error" /></IconButton>}>
                                        <ListItemText primary={`Server: ${allServers.find(s => s.id == serverId)?.hostname || 'Unknown'}`} secondary={`CPU Limit: ${limit}`} />
                                    </ListItem>
                                ))}
                            </List>
                        }
                    </Paper>

                    <UserSearchAndManage
                        existingMembers={members}
                        onMembersChange={setMembers}
                        searchTypes={['users']}
                    />

                </DialogContent>
                <DialogActions sx={{ position: 'relative', pr: 3, pb: 2 }}>
                    <Button onClick={onClose} disabled={loading}>Cancel</Button>
                    <Button type="submit" variant="contained" disabled={loading}>
                        {isEditMode ? 'Save Changes' : 'Create Group'}
                        {loading && <CircularProgress size={24} sx={{ position: 'absolute', top: '50%', left: '50%', marginTop: '-12px', marginLeft: '-12px' }} />}
                    </Button>
                </DialogActions>
            </Box>
        </Dialog>
    );
}

export default UserGroupModal;