import React, {useState, useEffect} from 'react';
import {
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogContentText,
    DialogTitle,
    TextField,
    CircularProgress,
    Alert,
    Box,
    FormControlLabel,
    Switch
} from '@mui/material';
import api from '../services/api';

function LocalUserModal({open, onClose, onSave, userToEdit}) {
    const [formData, setFormData] = useState({
        username: '',
        password: '',
        confirmPassword: '',
        is_admin: false
    });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const isEditMode = Boolean(userToEdit);

    useEffect(() => {
        if (isEditMode && userToEdit) {
            setFormData({
                username: userToEdit.username || '',
                password: '', // Password is not pre-filled for editing
                confirmPassword: '',
                is_admin: userToEdit.is_admin || false,
            });
        } else {
            setFormData({username: '', password: '', confirmPassword: '', is_admin: false});
        }
        setError('');
    }, [open, userToEdit, isEditMode]);

    const handleClose = () => {
        if (loading) return;
        onClose();
    };

    const handleInputChange = (event) => {
        const {name, value, type, checked} = event.target;
        setFormData(prev => ({...prev, [name]: type === 'checkbox' ? checked : value}));
    };

    const handleSubmit = async (event) => {
        event.preventDefault();
        // Validation
        if (!formData.username.trim()) {
            setError('Username is required.');
            return;
        }
        if (!isEditMode && !formData.password) { // Password required for new users
            setError('Password is required for new users.');
            return;
        }
        if (formData.password && formData.password !== formData.confirmPassword) {
            setError('Passwords do not match.');
            return;
        }
        if (formData.password && formData.password.length < 8) {
            setError('Password must be at least 8 characters long.');
            return;
        }

        setLoading(true);
        setError('');

        try {
            // Don't send empty password field on edit
            const payload = {
                username: formData.username.trim(),
                is_admin: formData.is_admin,
            };
            if (formData.password) {
                payload.password = formData.password;
            }

            if (isEditMode) {
                await api.put(`/api/admin/users/${userToEdit.id}`, payload);
            } else {
                await api.post('/api/admin/users', payload);
            }
            onSave();
            handleClose();
        } catch (err) {
            console.error("Failed to save user:", err);
            setError(err.response?.data?.message || `Failed to ${isEditMode ? 'update' : 'create'} user.`);
        } finally {
            setLoading(false);
        }
    };

    return (
        <Dialog open={open} onClose={handleClose} aria-labelledby="user-dialog-title">
            <DialogTitle id="user-dialog-title">{isEditMode ? 'Edit Local User' : 'Add New Local User'}</DialogTitle>
            <Box component="form" onSubmit={handleSubmit}>
                <DialogContent>
                    <DialogContentText sx={{mb: 2}}>
                        {isEditMode ? "Update user details. Leave password fields blank to keep the current password." : "Create a new local user account."}
                    </DialogContentText>
                    {error && <Alert severity="error" sx={{mb: 2}}>{error}</Alert>}
                    <TextField autoFocus margin="dense" id="username" name="username" label="Username" type="text"
                               fullWidth variant="outlined" value={formData.username} onChange={handleInputChange}
                               disabled={loading} required sx={{mb: 2}}/>
                    <TextField margin="dense" id="password" name="password"
                               label={isEditMode ? "New Password (Optional)" : "Password"} type="password" fullWidth
                               variant="outlined" value={formData.password} onChange={handleInputChange}
                               disabled={loading} required={!isEditMode} sx={{mb: 2}}/>
                    <TextField margin="dense" id="confirmPassword" name="confirmPassword" label="Confirm Password"
                               type="password" fullWidth variant="outlined" value={formData.confirmPassword}
                               onChange={handleInputChange} disabled={loading}/>
                    <FormControlLabel
                        control={<Switch checked={formData.is_admin} onChange={handleInputChange} name="is_admin"
                                         disabled={loading}/>}
                        label="Administrator Privileges"
                        sx={{mt: 1}}
                    />
                </DialogContent>
                <DialogActions sx={{position: 'relative', pr: 3, pb: 2}}>
                    <Button onClick={handleClose} disabled={loading} color="secondary">Cancel</Button>
                    <Button type="submit" disabled={loading} variant="contained" color="primary">
                        {isEditMode ? 'Save Changes' : 'Create User'}
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

export default LocalUserModal;