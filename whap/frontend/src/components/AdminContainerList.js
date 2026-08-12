import React from 'react';
import {
    Box,
    Button,
    Typography,
    Paper,
    TableContainer,
    Table,
    TableHead,
    TableBody,
    TableRow,
    TableCell,
    IconButton,
    Tooltip,
    CircularProgress,
    Chip,
    Stack,
} from '@mui/material';
import StopCircleIcon from '@mui/icons-material/StopCircle';
import DeleteForeverIcon from '@mui/icons-material/DeleteForever';
import EditIcon from "@mui/icons-material/Edit";
import AddIcon from "@mui/icons-material/Add";
import PersonIcon from '@mui/icons-material/Person';
import FolderIcon from '@mui/icons-material/Folder';
import SaveIcon from '@mui/icons-material/Save';

const stringToColor = (string) => {
    let hash = 0;
    for (let i = 0; i < string.length; i++) {
        hash = string.charCodeAt(i) + ((hash << 5) - hash);
    }
    let color = '#';
    for (let i = 0; i < 3; i++) {
        const value = (hash >> (i * 8)) & 0xFF;
        color += ('00' + value.toString(16)).substring(-2);
    }
    return color;
};

function AdminContainerList({containers, onStop, onDelete, onAddContainer, onEditContainer, stoppingContainerId}) {
    if (!containers || containers.length === 0) {
        return (
            <Box>
                <Button variant="contained" startIcon={<AddIcon/>} onClick={onAddContainer} size="small" sx={{mb: 2}}>
                    Manually Add Container
                </Button>
                <Typography sx={{textAlign: 'center', mt: 3, p: 2, color: 'text.secondary'}}>
                    No containers found.
                </Typography>
            </Box>
        );
    }

    return (
        <>
            <Box sx={{display: 'flex', justifyContent: 'flex-end', mb: 1}}>
                <Button variant="contained" startIcon={<AddIcon/>} onClick={onAddContainer} size="small">
                    Manually Add Container
                </Button>
            </Box>
            <TableContainer component={Paper}>
                <Table size="small" aria-label="all containers table">
                    <TableHead>
                        <TableRow>
                            <TableCell sx={{fontWeight: 'bold', width: '20%'}}>ID / Name</TableCell>
                            <TableCell sx={{fontWeight: 'bold', width: '30%'}}>Details</TableCell>
                            <TableCell sx={{fontWeight: 'bold', width: '20%'}}>Location</TableCell>
                            <TableCell sx={{fontWeight: 'bold', width: '15%'}}>Status</TableCell>
                            <TableCell align="right" sx={{fontWeight: 'bold', width: '15%'}}>Actions</TableCell>
                        </TableRow>
                    </TableHead>
                    <TableBody>
                        {containers.map((row) => {
                            const canStop = ['RUNNING', 'PAUSED', 'STARTING', 'ERROR'].includes(row.status);
                            const isStopping = stoppingContainerId === row.id;
                            const serverColor = stringToColor(row.server || 'unknown');

                            return (
                                <TableRow hover key={row.id}>
                                    {/* Column 1: ID & Container Name */}
                                    <TableCell valign="top">
                                        <Typography variant="subtitle2" sx={{fontWeight: 'bold'}}>
                                            #{row.id}
                                        </Typography>
                                        <Typography variant="caption" display="block" sx={{
                                            fontFamily: 'monospace',
                                            color: 'text.secondary',
                                            wordBreak: 'break-all'
                                        }}>
                                            {row.container_name || '-'}
                                        </Typography>
                                    </TableCell>

                                    {/* Column 2: Metadata (User, Project, Image) */}
                                    <TableCell valign="top">
                                        <Stack spacing={0.5}>
                                            <Box sx={{display: 'flex', alignItems: 'center'}}>
                                                <PersonIcon sx={{fontSize: 14, mr: 0.5, color: 'action.active'}}/>
                                                <Typography variant="body2" noWrap>{row.user_display}</Typography>
                                            </Box>
                                            <Box sx={{display: 'flex', alignItems: 'center'}}>
                                                <FolderIcon sx={{fontSize: 14, mr: 0.5, color: 'action.active'}}/>
                                                <Typography variant="body2" noWrap>{row.project}</Typography>
                                            </Box>
                                            <Box sx={{display: 'flex', alignItems: 'center'}}>
                                                <SaveIcon sx={{fontSize: 14, mr: 0.5, color: 'action.active'}}/>
                                                <Typography variant="caption" noWrap
                                                            title={row.image}>{row.image}</Typography>
                                            </Box>
                                        </Stack>
                                    </TableCell>

                                    {/* Column 3: Server & IP */}
                                    <TableCell valign="top">
                                        <Stack spacing={1} alignItems="flex-start">
                                            <Chip
                                                label={row.server}
                                                size="small"
                                                sx={{
                                                    height: 20,
                                                    fontSize: '0.7rem',
                                                    backgroundColor: serverColor + '20', // Add transparency
                                                    color: 'text.primary',
                                                    border: `1px solid ${serverColor}`,
                                                    fontWeight: 500
                                                }}
                                            />
                                            <Typography variant="caption"
                                                        sx={{fontFamily: 'monospace', display: 'block'}}>
                                                {row.ip_address || 'No IP'}
                                            </Typography>
                                        </Stack>
                                    </TableCell>

                                    {/* Column 4: Status */}
                                    <TableCell valign="top">
                                        <Chip
                                            label={row.status}
                                            color={
                                                row.status === 'RUNNING' ? 'success' :
                                                    row.status === 'STOPPED' ? 'default' :
                                                        row.status === 'ERROR' ? 'error' : 'warning'
                                            }
                                            size="small"
                                            variant={row.status === 'RUNNING' ? 'filled' : 'outlined'}
                                        />
                                    </TableCell>

                                    {/* Column 5: Actions */}
                                    <TableCell align="right" valign="top">
                                        <Box sx={{display: 'flex', justifyContent: 'flex-end'}}>
                                            <Tooltip title="Manually Edit Record">
                                                <IconButton size="small" color="primary"
                                                            onClick={() => onEditContainer(row)}>
                                                    <EditIcon fontSize="small"/>
                                                </IconButton>
                                            </Tooltip>
                                            <Tooltip title="Stop Container (via Ansible)">
                                                <span>
                                                    <IconButton size="small" color="warning"
                                                                onClick={() => onStop(row.id)}
                                                                disabled={!canStop || isStopping}>
                                                        {isStopping ? <CircularProgress size={18}/> :
                                                            <StopCircleIcon fontSize="small"/>}
                                                    </IconButton>
                                                </span>
                                            </Tooltip>
                                            <Tooltip title="Delete DB Record Only">
                                                <IconButton size="small" color="error" onClick={() => onDelete(row)}>
                                                    <DeleteForeverIcon fontSize="small"/>
                                                </IconButton>
                                            </Tooltip>
                                        </Box>
                                    </TableCell>
                                </TableRow>
                            );
                        })}
                    </TableBody>
                </Table>
            </TableContainer>
        </>
    );
}

export default AdminContainerList;