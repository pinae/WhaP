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
import DnsIcon from '@mui/icons-material/Dns'; // Server icon

function ComputeServerList({servers, onAddServer, onEditServer, isLoading, error}) {

    if (isLoading) {
        return <Box sx={{display: 'flex', justifyContent: 'center', p: 3}}><CircularProgress/></Box>;
    }

    return (
        <Paper elevation={2} sx={{p: 2}}>
            <Box sx={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2}}>
                <Typography variant="h6">Compute Servers</Typography>
                <Button
                    variant="contained"
                    startIcon={<AddIcon/>}
                    onClick={onAddServer}
                    size="small"
                >
                    Add Server
                </Button>
            </Box>
            {error && <Alert severity="error" sx={{mb: 2}}>{error}</Alert>}

            {servers && servers.length > 0 ? (
                <TableContainer>
                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell sx={{fontWeight: 'bold'}}>ID</TableCell>
                                <TableCell sx={{fontWeight: 'bold'}}>Hostname / IP</TableCell>
                                <TableCell sx={{fontWeight: 'bold'}}>SSH Port</TableCell>
                                <TableCell sx={{fontWeight: 'bold'}}>GPU Count</TableCell>
                                <TableCell align="right" sx={{fontWeight: 'bold'}}>Actions</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {servers.map((server) => (
                                <TableRow hover key={server.id}>
                                    <TableCell>{server.id}</TableCell>
                                    <TableCell>
                                        <Box sx={{display: 'flex', alignItems: 'center'}}>
                                            <DnsIcon sx={{mr: 1, fontSize: '1.1rem', color: 'action.active'}}/>
                                            {server.hostname}
                                        </Box>
                                    </TableCell>
                                    <TableCell>{server.ssh_port}</TableCell>
                                    <TableCell>{server.gpu_count}</TableCell>
                                    <TableCell align="right">
                                        <Tooltip title="Edit Server">
                                            <IconButton onClick={() => onEditServer(server)} size="small">
                                                <EditIcon fontSize="small"/>
                                            </IconButton>
                                        </Tooltip>
                                        {/* Add Delete button here if needed */}
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </TableContainer>
            ) : (
                <Typography sx={{textAlign: 'center', mt: 3, color: 'text.secondary'}}>
                    No compute servers configured yet.
                </Typography>
            )}
        </Paper>
    );
}

export default ComputeServerList;