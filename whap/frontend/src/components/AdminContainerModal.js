import React, { useState, useEffect, useMemo } from 'react';
import {
    Button, Dialog, DialogActions, DialogContent, DialogTitle, TextField,
    CircularProgress, Alert, Box, Grid, Select, MenuItem, InputLabel, FormControl,
    FormHelperText
} from '@mui/material';

function AdminContainerModal({
    open,
    onClose,
    onSave,
    containerToEdit,
    allProjects = [],
    allServers = [],
    allImages = [],
    allSshKeys = [],
    allStaticAddresses = [],
    allLocalUsers = [],
    loading,
    error,
}) {
    const isEditMode = Boolean(containerToEdit);

    const initialFormState = {
        user_type: 'local',
        local_user_id: '',
        ldap_uid: '',
        project_id: '',
        compute_server_id: '',
        image_name: '',
        ssh_key_id: '',
        static_address_id: '',
        gpus: '',
        status: 'RUNNING',
        container_name: '',
        ssh_command: '',
        directory_path: ''
    };

    const [formState, setFormState] = useState(initialFormState);

    useEffect(() => {
        if (isEditMode && containerToEdit) {
            let user_type = 'ldap';
            let local_user_id = '';
            let ldap_uid = '';
            const userDisplay = containerToEdit.user_display || '';
            const project = allProjects.find(p => p.name === containerToEdit.project);
            const server = allServers.find(s => s.hostname === containerToEdit.server);
            const image = allImages.find(i => i.id === containerToEdit.image); // Compare role name
            const sshKey = allSshKeys.find(k => k.name === containerToEdit.ssh_key_name && k.user_uid === containerToEdit.user_display.replace(/ \((Local|LDAP)\)/, ''));
            const staticAddress = allStaticAddresses.find(a => a.ip_address === containerToEdit.ip_address);

            if (userDisplay.includes('(Local)')) {
                user_type = 'local';
                const localUser = allLocalUsers.find(u => u.username === containerToEdit.username);
                if (localUser) {
                    local_user_id = localUser.id;
                }
            } else if (userDisplay.includes('(LDAP)')) {
                user_type = 'ldap';
                ldap_uid = containerToEdit.username;
            }

            setFormState({
                user_type,
                local_user_id,
                ldap_uid,
                project_id: project?.id || '',
                compute_server_id: server?.id || '',
                image_name: image?.id || '',
                ssh_key_id: sshKey?.id || '',
                static_address_id: staticAddress?.id || '',
                gpus: containerToEdit.gpus || '',
                status: containerToEdit.status || 'RUNNING',
                container_name: containerToEdit.container_name || '',
                ssh_command: containerToEdit.ssh_command || '',
                directory_path: containerToEdit.directory_path || ''
            });
        } else {
            setFormState(initialFormState);
        }
    }, [open, containerToEdit, isEditMode, allProjects, allServers, allImages, allSshKeys, allStaticAddresses, allLocalUsers]);

    const handleInputChange = (event) => {
        const { name, value } = event.target;
        const newState = { ...formState, [name]: value };
        if (name === 'user_type') {
            newState.local_user_id = '';
            newState.ldap_uid = '';
            newState.ssh_key_id = '';
        }
        if (name === 'local_user_id' || name === 'ldap_uid') {
            newState.ssh_key_id = '';
        }
        setFormState(newState);
    };

    const handleSubmit = (event) => {
        event.preventDefault();
        let user_identifier;
        if (formState.user_type === 'local' && formState.local_user_id) {
            user_identifier = `local:${formState.local_user_id}`;
        } else if (formState.user_type === 'ldap' && formState.ldap_uid) {
            user_identifier = `ldap:${formState.ldap_uid.trim()}`;
        } else {
            onSave(null, isEditMode, null, "A user must be selected or specified.");
            return;
        }
        const payload = { ...formState, user_identifier };
        delete payload.user_type;
        delete payload.local_user_id;
        delete payload.ldap_uid;
        onSave(payload, isEditMode, containerToEdit?.id);
    };

    const filteredSshKeys = useMemo(() => {
        let userIdentifier;
        if (formState.user_type === 'local' && formState.local_user_id) {
            userIdentifier = `local:${formState.local_user_id}`;
        } else if (formState.user_type === 'ldap' && formState.ldap_uid) {
            userIdentifier = `ldap:${formState.ldap_uid.trim()}`;
        }
        if (!userIdentifier) return [];
        return allSshKeys.filter(key => key.user_uid === userIdentifier);
    }, [formState.user_type, formState.local_user_id, formState.ldap_uid, allSshKeys]);

    return (
        <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
            <DialogTitle>{isEditMode ? 'Manually Edit Container Record' : 'Manually Create Container Record'}</DialogTitle>
            <Box component="form" onSubmit={handleSubmit}>
                <DialogContent>
                    <Alert severity="warning" sx={{ mb: 2 }}>
                        For administrative use only. Changes here directly modify the database and do not affect running containers. Use with caution to fix inconsistencies.
                    </Alert>
                    {error && <Alert severity="error" sx={{mb: 2}}>{error}</Alert>}
                    <Grid container spacing={2}>
                        <Grid item xs={12} sm={4}>
                            <FormControl fullWidth>
                                <InputLabel>User Type</InputLabel>
                                <Select name="user_type" value={formState.user_type} label="User Type" onChange={handleInputChange}>
                                    <MenuItem value="local">Local User</MenuItem>
                                    <MenuItem value="ldap">LDAP User</MenuItem>
                                </Select>
                            </FormControl>
                        </Grid>
                        <Grid item xs={12} sm={8}>
                            {formState.user_type === 'local' ? (
                                <FormControl fullWidth required>
                                    <InputLabel>Local User</InputLabel>
                                    <Select name="local_user_id" value={formState.local_user_id} label="Local User" onChange={handleInputChange}>
                                        {allLocalUsers.map(user => <MenuItem key={user.id} value={user.id}>{user.username}</MenuItem>)}
                                    </Select>
                                </FormControl>
                            ) : (
                                <TextField name="ldap_uid" label="LDAP Username (uid)" value={formState.ldap_uid} onChange={handleInputChange} fullWidth required />
                            )}
                        </Grid>

                        <Grid item xs={12} sm={6}>
                            <FormControl fullWidth required>
                                <InputLabel>Project</InputLabel>
                                <Select name="project_id" value={formState.project_id} label="Project" onChange={handleInputChange}>
                                    {allProjects.map(p => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
                                </Select>
                            </FormControl>
                        </Grid>
                        <Grid item xs={12} sm={6}>
                            <FormControl fullWidth required>
                                <InputLabel>Compute Server</InputLabel>
                                <Select name="compute_server_id" value={formState.compute_server_id} label="Compute Server" onChange={handleInputChange}>
                                    {allServers.map(s => <MenuItem key={s.id} value={s.id}>{s.hostname}</MenuItem>)}
                                </Select>
                            </FormControl>
                        </Grid>

                        <Grid item xs={12} sm={6}>
                            <FormControl fullWidth required>
                                <InputLabel>Image</InputLabel>
                                <Select name="image_name" value={formState.image_name} label="Image" onChange={handleInputChange}>
                                     {allImages.map(i => <MenuItem key={i.id} value={i.id}>{i.name}</MenuItem>)}
                                </Select>
                                <FormHelperText>Corresponds to an Ansible role (e.g., worker_pytorch)</FormHelperText>
                            </FormControl>
                        </Grid>
                         <Grid item xs={12} sm={6}>
                            <FormControl fullWidth required>
                                <InputLabel>Status</InputLabel>
                                <Select name="status" value={formState.status} label="Status" onChange={handleInputChange}>
                                    {['PENDING', 'STARTING', 'RUNNING', 'PAUSING', 'PAUSED', 'STOPPING', 'STOPPED', 'DELETING', 'ERROR'].map(s => (
                                        <MenuItem key={s} value={s}>{s}</MenuItem>
                                    ))}
                                </Select>
                            </FormControl>
                        </Grid>

                        <Grid item xs={12} sm={6}>
                            <FormControl fullWidth>
                                <InputLabel>SSH Key</InputLabel>
                                <Select name="ssh_key_id" value={formState.ssh_key_id} label="SSH Key" onChange={handleInputChange} disabled={filteredSshKeys.length === 0}>
                                    <MenuItem value=""><em>None</em></MenuItem>
                                    {filteredSshKeys.map(k => <MenuItem key={k.id} value={k.id}>{k.name}</MenuItem>)}
                                </Select>
                                <FormHelperText>{(formState.local_user_id || formState.ldap_uid) && filteredSshKeys.length === 0 ? 'Selected user has no keys.' : 'Optional'}</FormHelperText>
                            </FormControl>
                        </Grid>
                         <Grid item xs={12} sm={6}>
                            <FormControl fullWidth>
                                <InputLabel>Static IP Address</InputLabel>
                                <Select name="static_address_id" value={formState.static_address_id} label="Static IP Address" onChange={handleInputChange}>
                                    <MenuItem value=""><em>None</em></MenuItem>
                                    {allStaticAddresses.map(a => (
                                         <MenuItem key={a.id} value={a.id} disabled={a.assigned_container_id && a.assigned_container_id !== containerToEdit?.id}>
                                            {a.ip_address} {a.assigned_container_id && a.assigned_container_id !== containerToEdit?.id ? `(In Use by C#${a.assigned_container_id})` : ''}
                                        </MenuItem>
                                    ))}
                                </Select>
                            </FormControl>
                        </Grid>

                        <Grid item xs={12} sm={4}>
                            <TextField name="gpus" label="GPUs" value={formState.gpus} onChange={handleInputChange} fullWidth helperText="e.g., 0 or 0,1" />
                        </Grid>
                         <Grid item xs={12} sm={8}>
                            <TextField name="container_name" label="Docker Container Name" value={formState.container_name} onChange={handleInputChange} fullWidth />
                        </Grid>
                         <Grid item xs={12}>
                            <TextField name="directory_path" label="Host Directory Path" value={formState.directory_path} onChange={handleInputChange} fullWidth />
                        </Grid>
                         <Grid item xs={12}>
                            <TextField name="ssh_command" label="SSH Command" value={formState.ssh_command} onChange={handleInputChange} fullWidth />
                        </Grid>
                    </Grid>
                </DialogContent>
                <DialogActions sx={{position: 'relative', pr: 3, pb: 2}}>
                     <Button onClick={onClose} disabled={loading}>Cancel</Button>
                    <Button type="submit" variant="contained" disabled={loading}>
                        {isEditMode ? 'Save Changes' : 'Create Record'}
                        {loading && <CircularProgress size={24} sx={{
                            position: 'absolute', top: '50%', left: '50%',
                            marginTop: '-12px', marginLeft: '-12px'
                        }}/>}
                    </Button>
                </DialogActions>
            </Box>
        </Dialog>
    );
}

export default AdminContainerModal;