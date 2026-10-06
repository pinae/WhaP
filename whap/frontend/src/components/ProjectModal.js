import React, { useState, useEffect } from 'react';
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
    Grid
} from '@mui/material';
import api from '../services/api';
import UserSearchAndManage from './UserSearchAndManage';

const PROJECT_NAME_REGEX = /^[a-zA-Z0-9][a-zA-Z0-9_.-]*$/;


function ProjectModal({ open, onClose, onProjectSaved, projectToEdit }) {
    const [projectName, setProjectName] = useState('');
    const [shares, setShares] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const isEditMode = Boolean(projectToEdit);

    useEffect(() => {
        if (open) {
            if (isEditMode && projectToEdit) {
                setProjectName(projectToEdit.name || '');
                // Fetch full project details including shares for editing
                const fetchDetails = async () => {
                    setLoading(true);
                    try {
                        const response = await api.get(`/api/projects/${projectToEdit.id}`);
                        setShares(response.data.shares.map(s => ({
                            user_uid: s.user_uid,
                            is_group_admin: s.is_writable // Remap for the component
                        })) || []);
                    } catch (err) {
                        console.log(err);
                        setError("Failed to load project share details.");
                    } finally {
                        setLoading(false);
                    }
                };
                fetchDetails();

            } else {
                setProjectName('');
                setShares([]);
            }
            setError('');
        }
    }, [open, projectToEdit, isEditMode]);

    const handleClose = () => {
        if (loading) return; // Prevent closing while loading
        setProjectName(''); // Reset form
        setError('');
        setShares([]);
        onClose();
    };

    const handleSharesChange = (newShares) => {
        setShares(newShares);
    };

    const handleSubmit = async (event) => {
        event.preventDefault();
        if (!projectName.trim()) {
            setError('Project name cannot be empty.');
            return;
        }
        if (!PROJECT_NAME_REGEX.test(projectName.trim())) {
            setError('Project name must start with a letter or number and contain only letters, numbers, underscores, hyphens, and dots.');
            return;
        }
        setLoading(true);
        setError('');

        try {
            const payload = {
                name: projectName.trim(),
                shares: shares.map(s => ({
                    user_uid: s.user_uid,
                    is_writable: s.is_group_admin // Remap back to backend field name
                }))
            };

            const response = isEditMode
                ? await api.put(`/api/projects/${projectToEdit.id}`, payload)
                : await api.post('/api/projects', payload);
            onProjectSaved(response.data);
            handleClose();
        } catch (err) {
            console.error("Failed to save project:", err);
            setError(err.response?.data?.message || 'Failed to save project. Please try again.');
        } finally {
            setLoading(false);
        }
    };

    return (
        <Dialog open={open} onClose={handleClose} aria-labelledby="form-dialog-title" maxWidth="md" fullWidth>
            <DialogTitle id="form-dialog-title">{isEditMode ? 'Edit Project' : 'Create New Project'}</DialogTitle>
            <Box component="form" onSubmit={handleSubmit}>
                <DialogContent>
                    <DialogContentText sx={{ mb: 2 }}>
                        Enter a name for your project. This will also be used for the directory name on the server.
                        It must start with a letter or number and can contain letters, numbers, underscores, hyphens, and dots.
                    </DialogContentText>
                    {error && <Alert severity="error" sx={{ mb: 2 }} data-testid="project-modal-error">{error}</Alert>}
                    <TextField
                        autoFocus
                        margin="dense"
                        id="projectName"
                        label="Project Name"
                        type="text"
                        fullWidth
                        variant="outlined"
                        value={projectName}
                        onChange={(e) => setProjectName(e.target.value)}
                        disabled={loading}
                        required
                        slotProps={{ htmlInput: { 'data-testid': 'project-name-input' } }}
                    />
                    {isEditMode && (
                        <Grid item xs={12} sx={{ mt: 2 }}>
                            <UserSearchAndManage
                                existingMembers={shares}
                                onMembersChange={handleSharesChange}
                                memberTypeLabel="Share with Users/Groups"
                                adminToggleLabel="Write Access"
                                searchTypes={['users', 'groups']}
                            />
                        </Grid>
                    )}
                </DialogContent>
                <DialogActions sx={{ position: 'relative', pr: 3, pb: 2 }}>
                    <Button onClick={handleClose} disabled={loading} color="secondary">
                        Cancel
                    </Button>
                    <Button type="submit" disabled={loading} variant="contained" color="primary"
                            data-testid="project-modal-submit">
                        {isEditMode ? 'Save Changes' : 'Create Project'}
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

export default ProjectModal;