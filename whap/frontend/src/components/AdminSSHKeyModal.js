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
    Grid,
    Select,
    MenuItem,
    InputLabel,
    FormControl
} from '@mui/material';

function AdminSSHKeyModal({
                              open,
                              onClose,
                              onSave,
                              keyToEdit,
                              allLocalUsers = [],
                              loading,
                              error,
                          }) {
    const isEditMode = Boolean(keyToEdit);

    const getInitialFormState = () => {
        if (isEditMode && keyToEdit) {
            const userIdentifier = keyToEdit.user_uid || '';
            const [userType, userId] = userIdentifier.split(':', 2);
            return {
                name: keyToEdit.name || '',
                public_key: keyToEdit.public_key || '',
                user_type: userType || 'local',
                local_user_id: userType === 'local' ? userId : '',
                ldap_uid: userType === 'ldap' ? userId : '',
            };
        }
        return {name: '', public_key: '', user_type: 'local', local_user_id: '', ldap_uid: ''};
    };

    const [formState, setFormState] = useState(getInitialFormState);

    useEffect(() => {
        setFormState(getInitialFormState());
    }, [open, keyToEdit]);

    const handleInputChange = (event) => {
        const {name, value} = event.target;
        const newState = {...formState, [name]: value};
        if (name === 'user_type') {
            newState.local_user_id = '';
            newState.ldap_uid = '';
        }
        setFormState(newState);
    };

    const handleSubmit = (event) => {
        event.preventDefault();

        const {name, public_key, user_type, local_user_id, ldap_uid} = formState;

        if (!name.trim() || !public_key.trim()) {
            onSave(null, isEditMode, null, "Key Name and Public Key are required.");
            return;
        }

        if (!public_key.trim().match(/^(ssh-rsa|ssh-dss|ssh-ed25519|ecdsa-sha2-nistp\d*)\s+/)) {
            onSave(null, isEditMode, null, 'Invalid public key format. Key should start with ssh-rsa, ssh-dss, ecdsa-..., or ssh-ed25519.');
            return;
        }

        let user_identifier;
        if (user_type === 'local' && local_user_id) {
            user_identifier = `local:${local_user_id}`;
        } else if (user_type === 'ldap' && ldap_uid.trim()) {
            user_identifier = `ldap:${ldap_uid.trim()}`;
        } else {
            onSave(null, isEditMode, null, "An owner must be selected or specified.");
            return;
        }

        const payload = {name: name.trim(), public_key: public_key.trim(), user_identifier};
        onSave(payload, isEditMode, keyToEdit?.id);
    };

    return (
        <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
            <DialogTitle>{isEditMode ? 'Edit SSH Key' : 'Create New SSH Key'}</DialogTitle>
            <Box component="form" onSubmit={handleSubmit}>
                <DialogContent>
                    {error && <Alert severity="error" sx={{mb: 2}}>{error}</Alert>}
                    <Grid container spacing={2}>
                        <Grid item xs={12} sm={4}>
                            <FormControl fullWidth>
                                <InputLabel>Owner Type</InputLabel>
                                <Select name="user_type" value={formState.user_type} label="Owner Type"
                                        onChange={handleInputChange} disabled={loading}>
                                    <MenuItem value="local">Local User</MenuItem>
                                    <MenuItem value="ldap">LDAP User</MenuItem>
                                </Select>
                            </FormControl>
                        </Grid>
                        <Grid item xs={12} sm={8}>
                            {formState.user_type === 'local' ? (
                                <FormControl fullWidth required disabled={loading}>
                                    <InputLabel>Local User Owner</InputLabel>
                                    <Select name="local_user_id" value={formState.local_user_id}
                                            label="Local User Owner" onChange={handleInputChange}>
                                        <MenuItem value=""><em>Select a user</em></MenuItem>
                                        {allLocalUsers.map(user => <MenuItem key={user.id}
                                                                             value={user.id}>{user.username}</MenuItem>)}
                                    </Select>
                                </FormControl>
                            ) : (
                                <TextField name="ldap_uid" label="LDAP Username (uid)" value={formState.ldap_uid}
                                           onChange={handleInputChange} fullWidth required disabled={loading}/>
                            )}
                        </Grid>
                        <Grid item xs={12}>
                            <TextField
                                name="name"
                                label="Key Name"
                                value={formState.name}
                                onChange={handleInputChange}
                                fullWidth
                                required
                                disabled={loading}
                                sx={{mt: 1}}
                            />
                        </Grid>
                        <Grid item xs={12}>
                            <TextField
                                name="public_key"
                                label="Public Key"
                                value={formState.public_key}
                                onChange={handleInputChange}
                                fullWidth
                                required
                                multiline
                                rows={5}
                                disabled={loading}
                                placeholder="Paste your public key here (e.g., ssh-ed25519 AAAAC3...)"
                            />
                        </Grid>
                    </Grid>
                </DialogContent>
                <DialogActions sx={{position: 'relative', pr: 3, pb: 2}}>
                    <Button onClick={onClose} disabled={loading}>Cancel</Button>
                    <Button type="submit" variant="contained" disabled={loading}>
                        {isEditMode ? 'Save Changes' : 'Create Key'}
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

export default AdminSSHKeyModal;