import React, { useState, useEffect } from 'react';
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
    Select,
    MenuItem,
    InputLabel,
    FormControl
} from '@mui/material';
import UserSearchAndManage from './UserSearchAndManage';

const PROJECT_NAME_REGEX = /^[a-zA-Z0-9][a-zA-Z0-9_.-]*$/;

function AdminProjectModal({
    open,
    onClose,
    onSave,
    projectToEdit,
    allLocalUsers = [],
    allGroups = [],
    loading,
    error,
}) {
    const isEditMode = Boolean(projectToEdit);

    const getInitialFormState = () => {
        if (isEditMode && projectToEdit) {
            const ownerDisplay = projectToEdit.owner_display || '';
            const isLocal = projectToEdit.owner_display.includes('(Local)');
            const isGroup = ownerDisplay.includes('(Group)');
            const username = ownerDisplay.replace(/ \((Local|LDAP|Group)\)/, '');

            let user_type = 'ldap';
            if (isLocal) user_type = 'local';
            if (isGroup) user_type = 'group';

            return {
                name: projectToEdit.name || '',
                user_type: user_type,
                local_user_id: isLocal ? (allLocalUsers.find(u => u.username === username)?.id || '') : '',
                ldap_uid: !isLocal && !isGroup ? username : '',
                group_id: isGroup ? (allGroups.find(g => g.name === username)?.id || '') : '',
                shares: projectToEdit.shares || []
            };
        }
        return { name: '', user_type: 'local', local_user_id: '', ldap_uid: '', group_id: '', shares: [] };
    };

    const [formState, setFormState] = useState(getInitialFormState);

    useEffect(() => {
        setFormState(getInitialFormState());
    }, [open, projectToEdit]);


    const handleInputChange = (event) => {
        const { name, value } = event.target;
        const newState = { ...formState, [name]: value };
        // When user type changes, reset the user selection
        if (name === 'user_type') {
            newState.local_user_id = '';
            newState.ldap_uid = '';
            newState.group_id = '';
        }
        setFormState(newState);
    };

    const handleSharesChange = (newShares) => {
        setFormState(prev => ({ ...prev, shares: newShares }));
    };

    const handleSubmit = (event) => {
        event.preventDefault();

        if (!PROJECT_NAME_REGEX.test(formState.name.trim())) {
            onSave(null, isEditMode, null, 'Project name must start with a letter or number and contain only letters, numbers, underscores, hyphens, and dots.');
            return;
        }

        let ownerData = {};
        if (formState.user_type === 'local' && formState.local_user_id) {
            ownerData = { owner_local_user_id: formState.local_user_id };
        } else if (formState.user_type === 'group' && formState.group_id) {
            ownerData = { owner_group_id: formState.group_id };
        } else if (formState.user_type === 'ldap' && formState.ldap_uid.trim()) {
            ownerData = { owner_uid: formState.ldap_uid.trim() };
        } else {
            onSave(null, isEditMode, null, "An owner must be selected or specified.");
            return;
        }

        const payload = {
            name: formState.name.trim(),
            ...ownerData,
            shares: formState.shares.map(s => ({ user_uid: s.user_uid, is_writable: s.is_group_admin }))
        };
        onSave(payload, isEditMode, projectToEdit?.id);
    };

    return (
        <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
            <DialogTitle>{isEditMode ? 'Edit Project' : 'Create New Project'}</DialogTitle>
            <Box component="form" onSubmit={handleSubmit}>
                <DialogContent>
                    {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
                    <Grid container spacing={2}>
                        <Grid item xs={12}>
                            <TextField
                                autoFocus
                                name="name"
                                label="Project Name"
                                value={formState.name}
                                onChange={handleInputChange}
                                fullWidth
                                required
                                disabled={loading}
                            />
                        </Grid>
                        <Grid item xs={12} sm={4}>
                            <FormControl fullWidth>
                                <InputLabel>Owner Type</InputLabel>
                                <Select
                                    variant="standard"
                                    name="user_type"
                                    value={formState.user_type}
                                    label="Owner Type"
                                    onChange={handleInputChange}
                                    disabled={loading}>
                                    <MenuItem value="local">Local User</MenuItem>
                                    <MenuItem value="ldap">LDAP User</MenuItem>
                                    <MenuItem value="group">Group</MenuItem>
                                </Select>
                            </FormControl>
                        </Grid>
                        <Grid item xs={12} sm={8}>
                            {formState.user_type === 'local' && (
                                <FormControl fullWidth required disabled={loading}>
                                    <InputLabel>Local User Owner</InputLabel>
                                    <Select
                                        variant="standard"
                                        name="local_user_id"
                                        value={formState.local_user_id}
                                        label="Local User Owner"
                                        onChange={handleInputChange}>
                                        <MenuItem value=""><em>Select a user</em></MenuItem>
                                        {allLocalUsers.map(user => <MenuItem key={user.id}
                                            value={user.id}>{user.username}</MenuItem>)}
                                    </Select>
                                </FormControl>
                            )}
                            {formState.user_type === 'ldap' && (
                                <TextField name="ldap_uid" label="LDAP Username (uid)" value={formState.ldap_uid}
                                    onChange={handleInputChange} fullWidth required disabled={loading} />
                            )}
                            {formState.user_type === 'group' && (
                                <FormControl fullWidth required disabled={loading}>
                                    <InputLabel>Group Owner</InputLabel>
                                    <Select
                                        variant="standard"
                                        name="group_id"
                                        value={formState.group_id}
                                        label="Group Owner"
                                        onChange={handleInputChange}>
                                        <MenuItem value=""><em>Select a group</em></MenuItem>
                                        {allGroups.map(group => <MenuItem key={group.id}
                                            value={group.id}>{group.name}</MenuItem>)}
                                    </Select>
                                </FormControl>
                            )}
                        </Grid>
                        {isEditMode && (
                            <Grid item xs={12}>
                                <UserSearchAndManage
                                    existingMembers={formState.shares.map(s => ({ user_uid: s.user_uid, is_group_admin: s.is_writable }))}
                                    onMembersChange={handleSharesChange}
                                    memberTypeLabel="Shared with"
                                    adminToggleLabel="Write Access"
                                    searchTypes={['users', 'groups']}
                                />
                            </Grid>
                        )}
                    </Grid>
                </DialogContent>
                <DialogActions sx={{ position: 'relative', pr: 3, pb: 2 }}>
                    <Button onClick={onClose} disabled={loading}>Cancel</Button>
                    <Button type="submit" variant="contained" disabled={loading}>
                        {isEditMode ? 'Save Changes' : 'Create Project'}
                        {loading && <CircularProgress size={24} sx={{
                            position: 'absolute', top: '50%', left: '50%',
                            marginTop: '-12px', marginLeft: '-12px'
                        }} />}
                    </Button>
                </DialogActions>
            </Box>
        </Dialog>
    );
}

export default AdminProjectModal;