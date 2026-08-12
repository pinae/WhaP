import React from 'react';
import {
    Box,
    Button,
    Typography,
    Paper,
    List,
    ListItem,
    ListItemText,
    CircularProgress,
    Alert,
    Tooltip,
    IconButton,
    Chip
} from '@mui/material';
import AddIcon from "@mui/icons-material/Add";
import EditIcon from "@mui/icons-material/Edit";
import GroupIcon from '@mui/icons-material/Group';
import DeleteIcon from '@mui/icons-material/Delete';

function UserGroupList({groups, onAddGroup, onEditGroup, onDeleteGroup, isLoading, error}) {
    return (
        <Paper elevation={2} sx={{p: 2}}>
            <Box sx={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2}}>
                <Typography variant="h6">My Groups</Typography>
                <Button variant="contained" startIcon={<AddIcon/>} onClick={onAddGroup} size="small">
                    Create Group
                </Button>
            </Box>
            {error && <Alert severity="error" sx={{mb: 2}}>{error}</Alert>}
            {isLoading ? (
                <Box sx={{display: 'flex', justifyContent: 'center', p: 3}}><CircularProgress/></Box>
            ) : groups.length > 0 ? (
                <List dense>
                    {groups.map((group) => (
                        <ListItem
                            key={group.id}
                            secondaryAction={
                                <>
                                    {group.is_group_admin && (
                                        <Chip label="Group Admin" color="secondary" size="small" variant="outlined"
                                              sx={{mr: 2}}/>
                                    )}
                                    <Tooltip
                                        title={group.is_group_admin ? "Edit Group" : "You are not an admin of this group"}>
                                        <span>
                                            <IconButton
                                                onClick={() => onEditGroup(group)}
                                                disabled={!group.is_group_admin}>
                                                <EditIcon/>
                                            </IconButton>
                                        </span>
                                    </Tooltip>
                                    {group.is_group_admin && (
                                        <Tooltip title="Delete Group">
                                            <IconButton
                                                edge="end"
                                                aria-label="delete"
                                                onClick={() => onDeleteGroup(group)} sx={{ml: 1}}>
                                                <DeleteIcon color="error"/>
                                            </IconButton>
                                        </Tooltip>
                                    )}
                                </>
                            }
                        >
                            <GroupIcon sx={{mr: 1.5, color: 'action.active'}}/>
                            <ListItemText
                                primary={group.name}
                                secondary={`Members: ${group.member_count}`}
                            />
                        </ListItem>
                    ))}
                </List>
            ) : (
                <Typography sx={{textAlign: 'center', mt: 3, color: 'text.secondary'}}>
                    You are not a member of any groups yet.
                </Typography>
            )}
        </Paper>
    );
}

export default UserGroupList;