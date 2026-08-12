import React, { useState } from 'react';
import {
    Box,
    Typography,
    List,
    ListItem,
    ListItemText,
    IconButton,
    Paper,
    Button,
    CircularProgress,
    Alert,
    Tooltip,
    Collapse,
    Dialog,
    DialogTitle,
    DialogContent,
    DialogContentText,
    DialogActions
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import KeyIcon from '@mui/icons-material/Key';
import VisibilityIcon from '@mui/icons-material/Visibility';
import api from '../services/api';

function SSHKeyList({ sshKeys, onAddKey, refreshKeys, isLoading, error }) {
  const [expandedKeyId, setExpandedKeyId] = useState(null);
  const [showConfirmDelete, setShowConfirmDelete] = useState(false);
  const [keyToDelete, setKeyToDelete] = useState(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  const toggleExpand = (keyId) => {
    setExpandedKeyId(prev => (prev === keyId ? null : keyId));
  };

  const openDeleteConfirm = (key) => {
    setKeyToDelete(key);
    setShowConfirmDelete(true);
    setDeleteError('');
  };

  const closeDeleteConfirm = () => {
    setKeyToDelete(null);
    setShowConfirmDelete(false);
  };

  const handleDeleteKey = async () => {
    if (!keyToDelete) return;
    setDeleteLoading(true);
    setDeleteError('');
    try {
      await api.delete(`/api/sshkeys/${keyToDelete.id}`);
      closeDeleteConfirm();
      refreshKeys(); // Callback to trigger data refresh in parent
    } catch (err) {
      console.error("Failed to delete SSH key:", err);
      setDeleteError(err.response?.data?.message || 'Failed to delete key.');
    } finally {
      setDeleteLoading(false);
    }
  };


  if (isLoading) {
    return <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}><CircularProgress /></Box>;
  }

  return (
    <>
      <Paper elevation={2} sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="h6">My SSH Keys</Typography>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={onAddKey}
            size="small"
          >
            Add SSH Key
          </Button>
        </Box>
         {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        {sshKeys && sshKeys.length > 0 ? (
          <List dense>
            {sshKeys.map((key) => (
              <React.Fragment key={key.id}>
                <ListItem
                  secondaryAction={
                    <>
                     <Tooltip title="Show Public Key">
                         <IconButton edge="end" aria-label="show" onClick={() => toggleExpand(key.id)} size="small" sx={{ mr: 0.5 }}>
                             <VisibilityIcon fontSize="small"/>
                         </IconButton>
                     </Tooltip>
                      <Tooltip title="Delete Key">
                        <IconButton edge="end" aria-label="delete" onClick={() => openDeleteConfirm(key)} size="small">
                          <DeleteIcon fontSize="small"/>
                        </IconButton>
                      </Tooltip>
                    </>
                  }
                >
                   <KeyIcon sx={{ mr: 1.5, color: 'action.active' }} />
                  <ListItemText
                    primary={key.name}
                    // secondary={`Created: ${new Date(key.created_at).toLocaleDateString()}`} // Optional: Add created date
                  />
                </ListItem>
                <Collapse in={expandedKeyId === key.id} timeout="auto" unmountOnExit>
                   <Box sx={{ pl: 4, pr: 2, pb: 1, wordBreak: 'break-all', fontStyle: 'italic', color: 'text.secondary' }}>
                     <Typography variant="caption" component="pre" sx={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace' }}>
                         {key.public_key}
                     </Typography>
                   </Box>
                 </Collapse>
              </React.Fragment>
            ))}
          </List>
        ) : (
          <Typography sx={{ textAlign: 'center', mt: 3, color: 'text.secondary' }}>
            You haven't added any SSH keys yet. Add one to enable passwordless login to containers.
          </Typography>
        )}
      </Paper>

      {/* Delete Confirmation Dialog */}
       <Dialog
         open={showConfirmDelete}
         onClose={closeDeleteConfirm}
         aria-labelledby="alert-dialog-title"
         aria-describedby="alert-dialog-description"
       >
         <DialogTitle id="alert-dialog-title">Confirm Delete</DialogTitle>
         <DialogContent>
           <DialogContentText id="alert-dialog-description">
             Are you sure you want to delete the SSH key named "{keyToDelete?.name}"? This action cannot be undone.
           </DialogContentText>
            {deleteError && <Alert severity="error" sx={{ mt: 2 }}>{deleteError}</Alert>}
         </DialogContent>
         <DialogActions sx={{ position: 'relative' }}>
           <Button onClick={closeDeleteConfirm} disabled={deleteLoading}>Cancel</Button>
           <Button onClick={handleDeleteKey} color="error" autoFocus disabled={deleteLoading}>
             Delete
              {deleteLoading && (
                  <CircularProgress size={20} sx={{ position: 'absolute', top: '50%', left: '50%', marginTop: '-10px', marginLeft: '-10px' }}/>
              )}
           </Button>
         </DialogActions>
       </Dialog>
    </>
  );
}

export default SSHKeyList;