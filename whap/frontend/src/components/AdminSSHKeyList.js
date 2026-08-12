import React from 'react';
import {
    Box, Button, Typography, Paper, TableContainer, Table, TableHead,
    TableBody, TableRow, TableCell, IconButton, Tooltip
} from '@mui/material';
import AddIcon from "@mui/icons-material/Add";
import EditIcon from "@mui/icons-material/Edit";
import DeleteIcon from "@mui/icons-material/Delete";

function AdminSSHKeyList({sshKeys, onAddKey, onEditKey, onDeleteKey}) {
    return (
        <Paper elevation={2} sx={{p: 2}}>
            <Box sx={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2}}>
                <Typography variant="h6">All SSH Keys</Typography>
                <Button variant="contained" startIcon={<AddIcon/>} onClick={onAddKey} size="small">
                    Add SSH Key
                </Button>
            </Box>
            <TableContainer>
                <Table stickyHeader size="small" aria-label="all ssh keys table">
                    <TableHead>
                        <TableRow>
                            <TableCell sx={{fontWeight: 'bold'}}>ID</TableCell>
                            <TableCell sx={{fontWeight: 'bold'}}>Key Name</TableCell>
                            <TableCell sx={{fontWeight: 'bold'}}>Owner</TableCell>
                            <TableCell sx={{fontWeight: 'bold'}}>Key Preview</TableCell>
                            <TableCell sx={{fontWeight: 'bold'}} align="right">Actions</TableCell>
                        </TableRow>
                    </TableHead>
                    <TableBody>
                        {sshKeys.map((key) => (
                            <TableRow hover key={key.id}>
                                <TableCell>{key.id}</TableCell>
                                <TableCell>{key.name}</TableCell>
                                <TableCell>{key.user_uid}</TableCell>
                                <TableCell sx={{fontFamily: 'monospace', fontSize: '0.8rem'}}>
                                    {key.public_key.substring(0, 40)}...
                                </TableCell>
                                <TableCell align="right">
                                    <Tooltip title="Edit SSH Key">
                                        <IconButton size="small" color="primary" onClick={() => onEditKey(key)}>
                                            <EditIcon fontSize="small"/>
                                        </IconButton>
                                    </Tooltip>
                                    <Tooltip title="Delete SSH Key">
                                        <IconButton size="small" color="error" onClick={() => onDeleteKey(key)}>
                                            <DeleteIcon fontSize="small"/>
                                        </IconButton>
                                    </Tooltip>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </TableContainer>
        </Paper>
    );
}

export default AdminSSHKeyList;