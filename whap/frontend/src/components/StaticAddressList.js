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
    Tooltip,
    Chip
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import LinkOffIcon from '@mui/icons-material/LinkOff';

function StaticAddressList({addresses, servers, onAddAddress, onEditAddress, onDeleteAddress, onFreeAddress, isLoading, error}) {

    // Create a map for quick server hostname lookup
    const serverMap = React.useMemo(() => {
        return servers.reduce((acc, server) => {
            acc[server.id] = server.hostname;
            return acc;
        }, {});
    }, [servers]);

    const getServerNames = (serverIds) => {
        if (!serverIds || serverIds.length === 0) return 'None';
        return serverIds.map(id => serverMap[id] || `ID:${id}`).join(', ');
    }

    if (isLoading) {
        return <Box sx={{display: 'flex', justifyContent: 'center', p: 3}}><CircularProgress/></Box>;
    }

    return (
        <Paper elevation={2} sx={{p: 2}}>
            <Box sx={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2}}>
                <Typography variant="h6">Static IP / MAC Addresses</Typography>
                <Button variant="contained" startIcon={<AddIcon/>} onClick={onAddAddress} size="small">
                    Add Address
                </Button>
            </Box>
            {error && <Alert severity="error" sx={{mb: 2}}>{error}</Alert>}

            {addresses && addresses.length > 0 ? (
                <TableContainer>
                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell sx={{fontWeight: 'bold'}}>IP Address</TableCell>
                                <TableCell sx={{fontWeight: 'bold'}}>MAC Address</TableCell>
                                <TableCell sx={{fontWeight: 'bold'}}>Network</TableCell>
                                <TableCell sx={{fontWeight: 'bold'}}>Available Servers</TableCell>
                                <TableCell sx={{fontWeight: 'bold'}}>Comment</TableCell>
                                <TableCell sx={{fontWeight: 'bold'}}>Assigned To</TableCell>
                                <TableCell align="right" sx={{fontWeight: 'bold'}}>Actions</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {addresses.map((addr) => (
                                <TableRow hover key={addr.id}>
                                    <TableCell sx={{fontFamily: 'monospace'}}>{addr.ip_address}</TableCell>
                                    <TableCell sx={{fontFamily: 'monospace'}}>{addr.mac_address}</TableCell>
                                    <TableCell>{addr.network_name || 'N/A'}</TableCell>
                                    <TableCell
                                        sx={{fontSize: '0.8rem'}}>{getServerNames(addr.available_server_ids)}</TableCell>
                                    <TableCell>{addr.comment}</TableCell>
                                    <TableCell>
                                        {addr.assigned_container_id
                                            ? <Chip
                                                label={`Cont. #${addr.assigned_container_id} (${addr.assigned_container_user || '?'})`}
                                                size="small" variant="outlined"/>
                                            : <Chip label="Free" size="small" color="success" variant="outlined"/>
                                        }
                                    </TableCell>
                                    <TableCell align="right">
                                        <Tooltip title="Edit Address">
                                            <IconButton onClick={() => onEditAddress(addr)} size="small">
                                                <EditIcon fontSize="small"/>
                                            </IconButton>
                                        </Tooltip>
                                        <Tooltip title="Free Address">
                                            <span> {/* Span needed for tooltip on disabled button */}
                                                <IconButton
                                                    onClick={() => onFreeAddress(addr)}
                                                    size="small"
                                                    color="warning"
                                                    disabled={!addr.assigned_container_id} // Disable if not assigned
                                                >
                                                    <LinkOffIcon fontSize="small" />
                                                </IconButton>
                                            </span>
                                        </Tooltip>
                                        <Tooltip title="Delete Address">
                                    <span> {/* Span needed for tooltip on potentially disabled button */}
                                        <IconButton
                                            onClick={() => onDeleteAddress(addr)}
                                            size="small"
                                            color="error"
                                            disabled={!!addr.assigned_container_id} // Disable delete if assigned
                                        >
                                        <DeleteIcon fontSize="small"/>
                                    </IconButton>
                                    </span>
                                        </Tooltip>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </TableContainer>
            ) : (
                <Typography sx={{textAlign: 'center', mt: 3, color: 'text.secondary'}}>
                    No static addresses configured yet.
                </Typography>
            )}
        </Paper>
    );
}

export default StaticAddressList;