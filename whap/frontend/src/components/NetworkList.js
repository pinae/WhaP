import React from 'react';
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
    Tooltip
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';

// Helper to calculate netmask from prefix size (IPv4)
const getNetmask = (prefixSize) => {
    if (prefixSize < 0 || prefixSize > 32) return 'Invalid';
    const mask = (0xFFFFFFFF << (32 - prefixSize)) & 0xFFFFFFFF;
    return [
        (mask >> 24) & 0xFF,
        (mask >> 16) & 0xFF,
        (mask >> 8) & 0xFF,
        mask & 0xFF
    ].join('.');
};

function NetworkList({networks, onAdd, onEdit, onDelete, isLoading, error}) {
    if (isLoading) {
        return <Box sx={{display: 'flex', justifyContent: 'center', p: 3}}><CircularProgress/></Box>;
    }

    return (
        <Paper elevation={2} sx={{p: 2}}>
            <Box sx={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2}}>
                <Typography variant="h6">Configured Networks</Typography>
                <Button variant="contained" startIcon={<AddIcon/>} onClick={onAdd} size="small">
                    Add Network
                </Button>
            </Box>
            {error && <Alert severity="error" sx={{mb: 2}}>{error}</Alert>}

            {networks && networks.length > 0 ? (
                <TableContainer>
                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell sx={{fontWeight: 'bold'}}>Name</TableCell>
                                <TableCell sx={{fontWeight: 'bold'}}>Subnet</TableCell>
                                <TableCell sx={{fontWeight: 'bold'}}>Netmask</TableCell>
                                <TableCell sx={{fontWeight: 'bold'}}>Gateway</TableCell>
                                <TableCell align="right" sx={{fontWeight: 'bold'}}>Actions</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {networks.map((net) => (
                                <TableRow hover key={net.id}>
                                    <TableCell>{net.name}</TableCell>
                                    <TableCell
                                        sx={{fontFamily: 'monospace'}}>{net.base_ip}/{net.prefix_size}</TableCell>
                                    <TableCell sx={{fontFamily: 'monospace'}}>{getNetmask(net.prefix_size)}</TableCell>
                                    <TableCell sx={{fontFamily: 'monospace'}}>{net.gateway}</TableCell>
                                    <TableCell align="right">
                                        <Tooltip title="Edit Network">
                                            <IconButton onClick={() => onEdit(net)} size="small">
                                                <EditIcon fontSize="small"/>
                                            </IconButton>
                                        </Tooltip>
                                        <Tooltip title="Delete Network">
                                            <IconButton onClick={() => onDelete(net)} size="small" color="error">
                                                <DeleteIcon fontSize="small"/>
                                            </IconButton>
                                        </Tooltip>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </TableContainer>
            ) : (
                <Typography sx={{textAlign: 'center', mt: 3, color: 'text.secondary'}}>
                    No networks configured yet.
                </Typography>
            )}
        </Paper>
    );
}

export default NetworkList;