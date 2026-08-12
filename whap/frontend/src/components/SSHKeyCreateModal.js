import React, { useState } from 'react';
import { Button, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, TextField, CircularProgress, Alert, Box } from '@mui/material';
import api from '../services/api';

function SSHKeyCreateModal({ open, onClose, onKeyCreated }) {
  const [keyName, setKeyName] = useState('');
  const [publicKey, setPublicKey] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleClose = () => {
    if (loading) return;
    setKeyName('');
    setPublicKey('');
    setError('');
    onClose();
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!keyName.trim() || !publicKey.trim()) {
      setError('Both key name and public key are required.');
      return;
    }
    // Basic validation for public key format (client-side)
    if (!publicKey.trim().match(/^(ssh-rsa|ssh-dss|ssh-ed25519|ecdsa-sha2-nistp\d*)\s+/)) {
        setError('Invalid public key format. Key should start with ssh-rsa, ssh-dss, ecdsa-..., or ssh-ed25519.');
        return;
    }

    setLoading(true);
    setError('');

    try {
      const response = await api.post('/api/sshkeys', {
        name: keyName.trim(),
        public_key: publicKey.trim(),
      });
      onKeyCreated(response.data); // Pass the new key data back
      handleClose(); // Close modal on success
    } catch (err) {
      console.error("Failed to add SSH key:", err);
      setError(err.response?.data?.message || 'Failed to add SSH key. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} aria-labelledby="sshkey-dialog-title" maxWidth="sm" fullWidth>
      <DialogTitle id="sshkey-dialog-title">Add New SSH Public Key</DialogTitle>
      <Box component="form" onSubmit={handleSubmit}>
        <DialogContent>
          <DialogContentText sx={{ mb: 2 }}>
            Give your key a recognizable name and paste the entire public key string (usually starts with ssh-rsa, ssh-ed25519, etc. and ends with user@host).
          </DialogContentText>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
          <TextField
            autoFocus
            margin="dense"
            id="keyName"
            label="Key Name"
            type="text"
            fullWidth
            variant="outlined"
            value={keyName}
            onChange={(e) => setKeyName(e.target.value)}
            disabled={loading}
            required
            sx={{ mb: 2 }}
          />
           <TextField
            margin="dense"
            id="publicKey"
            label="Public Key String"
            type="text"
            fullWidth
            multiline
            rows={4}
            variant="outlined"
            value={publicKey}
            onChange={(e) => setPublicKey(e.target.value)}
            disabled={loading}
            required
            placeholder="Paste your public key here (e.g., ssh-ed25519 AAAAC3NzaC1lZDI1NTE5... user@host)"
          />
        </DialogContent>
        <DialogActions sx={{ position: 'relative', pr: 3, pb: 2 }}>
          <Button onClick={handleClose} disabled={loading} color="secondary">
            Cancel
          </Button>
          <Button type="submit" disabled={loading} variant="contained" color="primary">
            Save Key
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

export default SSHKeyCreateModal;