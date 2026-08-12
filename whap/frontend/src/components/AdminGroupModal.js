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
    Typography,
    FormGroup,
    FormControlLabel,
    Checkbox
} from '@mui/material';
import UserSearchAndManage from './UserSearchAndManage';
import ImageWhitelistSelector from "./ImageWhitelistSelector";

function AdminGroupModal({open, onClose, onSave, groupToEdit, allServers = [], allImages, loading, error}) {
    const isEditMode = Boolean(groupToEdit);
    const [name, setName] = useState('');
    const [selectedImages, setSelectedImages] = useState([]);
    const [selectedServerIds, setSelectedServerIds] = useState(new Set());
    const [members, setMembers] = useState([]);

    useEffect(() => {
        if (isEditMode && groupToEdit) {
            setName(groupToEdit.name || '');
            setSelectedImages(groupToEdit.image_whitelist || []);
            setSelectedServerIds(new Set(groupToEdit.accessible_server_ids || []));
            setMembers(groupToEdit.members || []);
        } else {
            setName('');
            setSelectedImages([]);
            setSelectedServerIds(new Set());
            setMembers([]);
        }
    }, [open, groupToEdit]);

    const handleServerCheckboxChange = (event) => {
        const serverId = parseInt(event.target.value, 10);
        setSelectedServerIds(prev => {
            const newSet = new Set(prev);
            if (event.target.checked) {
                newSet.add(serverId);
            } else {
                newSet.delete(serverId);
            }
            return newSet;
        });
    };

    const handleSubmit = (event) => {
        event.preventDefault();
        const payload = {
            name: name.trim(),
            image_whitelist: selectedImages,
            accessible_server_ids: Array.from(selectedServerIds),
            members: members
        };
        onSave(payload, isEditMode, groupToEdit?.id);
    };

    return (
        <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
            <DialogTitle>{isEditMode ? 'Edit Group' : 'Create New Group'}</DialogTitle>
            <Box component="form" onSubmit={handleSubmit}>
                <DialogContent>
                    {error && <Alert severity="error" sx={{mb: 2}}>{error}</Alert>}
                    <TextField
                        autoFocus
                        margin="dense"
                        id="name"
                        label="Group Name"
                        type="text"
                        fullWidth
                        variant="outlined"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        disabled={loading || (isEditMode && groupToEdit.id === 0)}
                        required
                    />
                    {isEditMode && (
                       <UserSearchAndManage
                           existingMembers={members}
                           onMembersChange={setMembers}
                           searchTypes={['users']}
                       />
                    )}
                    <ImageWhitelistSelector
                       allImages={allImages}
                       selectedImages={selectedImages}
                       onSelectionChange={setSelectedImages}
                       disabled={loading}
                    />
                    <Typography variant="subtitle1" sx={{mt: 2, mb: 1}}>Accessible Compute Servers:</Typography>
                    <FormGroup
                        sx={{maxHeight: '200px', overflowY: 'auto', border: '1px solid #ccc', borderRadius: 1, p: 1}}>
                        <Grid container>
                            {allServers.map((server) => (
                                <Grid item xs={6} key={server.id}>
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
                </DialogContent>
                <DialogActions sx={{position: 'relative', pr: 3, pb: 2}}>
                    <Button onClick={onClose} disabled={loading}>Cancel</Button>
                    <Button type="submit" variant="contained" disabled={loading}>
                        {isEditMode ? 'Save Changes' : 'Create Group'}
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

export default AdminGroupModal;