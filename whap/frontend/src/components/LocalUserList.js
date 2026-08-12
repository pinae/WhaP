import React, {useContext} from 'react';
import {
    Box,
    Typography,
    Paper,
    Button,
    CircularProgress,
    Alert,
    TableContainer,
    Table,
    TableHead,
    TableBody,
    TableRow,
    TableCell,
    IconButton,
    Tooltip,
    Chip
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import {AuthContext} from '../contexts/AuthContext'; // To check current user for self-delete

// Helper to format date
const formatDate = (isoString) => {
    if (!isoString) return 'N/A';
    try {
        return new Date(isoString).toLocaleString();
    } catch (e) {
        return 'Invalid Date';
    }
};

function LocalUserList({users, onAddUser, onEditUser, onDeleteUser, isLoading, error}) {
    const {user: currentUser} = useContext(AuthContext); // Get the currently logged-in user

    if (isLoading) {
        return <Box sx={{display: 'flex', justifyContent: 'center', p: 3}}><CircularProgress/></Box>;
    }

    return (
        <Paper elevation={2} sx={{p: 2}}>
            <Box sx={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2}}>
                <Typography variant="h6">Local User Accounts</Typography>
                <Button variant="contained" startIcon={<AddIcon/>} onClick={onAddUser} size="small">
                    Add User
                </Button>
            </Box>
            {error && <Alert severity="error" sx={{mb: 2}}>{error}</Alert>}

            {users && users.length > 0 ? (
                <TableContainer>
                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell sx={{fontWeight: 'bold'}}>ID</TableCell>
                                <TableCell sx={{fontWeight: 'bold'}}>Username</TableCell>
                                <TableCell sx={{fontWeight: 'bold'}}>Admin Status</TableCell>
                                <TableCell sx={{fontWeight: 'bold'}}>Created</TableCell>
                                <TableCell align="right" sx={{fontWeight: 'bold'}}>Actions</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {users.map((user) => {
                                // Check if the row user is the currently logged-in user
                                const isSelf = currentUser && currentUser.id === `local:${user.id}`;
                                return (
                                    <TableRow hover key={user.id}>
                                        <TableCell>{user.id}</TableCell>
                                        <TableCell>{user.username}</TableCell>
                                        <TableCell>
                                            {user.is_admin
                                                ?
                                                <Chip label="Admin" color="secondary" size="small" variant="outlined"/>
                                                : <Chip label="User" size="small"/>
                                            }
                                        </TableCell>
                                        <TableCell>{formatDate(user.created_at)}</TableCell>
                                        <TableCell align="right">
                                            <Tooltip title="Edit User">
                                                <IconButton onClick={() => onEditUser(user)} size="small">
                                                    <EditIcon fontSize="small"/>
                                                </IconButton>
                                            </Tooltip>
                                            <Tooltip title={isSelf ? "Cannot delete your own account" : "Delete User"}>
                                        <span> {/* Span is necessary for tooltip on disabled button */}
                                            <IconButton onClick={() => onDeleteUser(user)} size="small" color="error"
                                                        disabled={isSelf}>
                                            <DeleteIcon fontSize="small"/>
                                        </IconButton>
                                        </span>
                                            </Tooltip>
                                        </TableCell>
                                    </TableRow>
                                );
                            })}
                        </TableBody>
                    </Table>
                </TableContainer>
            ) : (
                <Typography sx={{textAlign: 'center', mt: 3, color: 'text.secondary'}}>
                    No local users found.
                </Typography>
            )}
        </Paper>
    );
}

export default LocalUserList;