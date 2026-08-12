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
    Tooltip
} from '@mui/material';
import AddIcon from "@mui/icons-material/Add";
import EditIcon from "@mui/icons-material/Edit";
import DeleteIcon from "@mui/icons-material/Delete";
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';

function AdminGroupList({groups, onAddGroup, onEditGroup, onDeleteGroup}) {
    return (
        <Paper elevation={2} sx={{p: 2}}>
            <Box sx={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2}}>
                <Typography variant="h6">User Groups</Typography>
                <Button variant="contained" startIcon={<AddIcon/>} onClick={onAddGroup} size="small">
                    Add Group
                </Button>
            </Box>
            <TableContainer>
                <Table stickyHeader size="small" aria-label="all groups table">
                    <TableHead>
                        <TableRow>
                            <TableCell sx={{fontWeight: 'bold'}}>ID</TableCell>
                            <TableCell sx={{fontWeight: 'bold'}}>Group Name</TableCell>
                            <TableCell sx={{fontWeight: 'bold'}}>Members</TableCell>
                            <TableCell sx={{fontWeight: 'bold'}} align="right">Actions</TableCell>
                        </TableRow>
                    </TableHead>
                    <TableBody>
                        {groups.map((group) => (
                            <TableRow hover key={group.id}>
                                <TableCell>{group.id}</TableCell>
                                <TableCell>
                                    <Box sx={{display: 'flex', alignItems: 'center'}}>
                                        {group.id === 0 && <AdminPanelSettingsIcon color="secondary"
                                                                                   sx={{mr: 1, fontSize: '1.2rem'}}/>}
                                        {group.name}
                                    </Box>
                                </TableCell>
                                <TableCell>{group.member_count}</TableCell>
                                <TableCell align="right">
                                    <Tooltip title="Edit Group">
                                        <IconButton size="small" color="primary" onClick={() => onEditGroup(group)}>
                                            <EditIcon fontSize="small"/>
                                        </IconButton>
                                    </Tooltip>
                                    <Tooltip title={group.id === 0 ? "Admin group cannot be deleted" : "Delete Group"}>
                                        <span>
                                            <IconButton size="small" color="error" onClick={() => onDeleteGroup(group)}
                                                        disabled={group.id === 0}>
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
        </Paper>
    );
}

export default AdminGroupList;