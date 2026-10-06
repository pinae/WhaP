import React, {useState, useEffect, useCallback} from 'react';
import {
    Box,
    TextField,
    List,
    ListItem,
    ListItemText,
    IconButton,
    CircularProgress,
    Typography,
    Paper,
    Switch,
    FormControlLabel
} from '@mui/material';
import AddCircleOutlineIcon from '@mui/icons-material/AddCircleOutline';
import RemoveCircleOutlineIcon from '@mui/icons-material/RemoveCircleOutline';
import debounce from 'lodash.debounce';
import api from '../services/api';

function UserSearchAndManage({
                                 existingMembers = [],
                                 onMembersChange,
                                 memberTypeLabel = "Group Members",
                                 adminToggleLabel = "Group Admin",
                                 searchTypes = ['users']
                             }) {
    const [searchTerm, setSearchTerm] = useState('');
    const [searchResults, setSearchResults] = useState([]);
    const [loading, setLoading] = useState(false);
    const [currentMembers, setCurrentMembers] = useState(existingMembers);

    useEffect(() => {
        setCurrentMembers(existingMembers);
    }, [existingMembers]);

    const debouncedSearch = useCallback(
        debounce(async (query) => {
            if (query.length < 2) {
                setSearchResults([]);
                return;
            }
            setLoading(true);
            try {
                const requests = [];
                if (searchTypes.includes('users')) {
                    requests.push(api.get(`/api/users/search?q=${query}`));
                }
                if (searchTypes.includes('groups')) {
                    requests.push(api.get(`/api/groups/search?q=${query}`));
                }

                const responses = await Promise.all(requests);
                const combinedResults = responses.flatMap(res => res.data);
                const memberIds = new Set(currentMembers.map(m => m.user_uid));
                // Filter out users who are already members
                const finalResults = combinedResults.filter(u => !memberIds.has(u.id));
                setSearchResults(finalResults);
            } catch (error) {
                console.error("Failed to search " + searchTypes.join(' or ') + ":", error);
                setSearchResults([]);
            } finally {
                setLoading(false);
            }
        }, 500),
        [currentMembers, searchTypes]
    );

    useEffect(() => {
        debouncedSearch(searchTerm);
        return () => debouncedSearch.cancel();
    }, [searchTerm, debouncedSearch]);

    const handleAddMember = (user) => {
        const newMembers = [...currentMembers, {user_uid: user.id, is_group_admin: false}];
        setCurrentMembers(newMembers);
        onMembersChange(newMembers);
        setSearchTerm('');
        setSearchResults([]);
    };

    const handleRemoveMember = (user_uid_to_remove) => {
        const newMembers = currentMembers.filter(m => m.user_uid !== user_uid_to_remove);
        setCurrentMembers(newMembers);
        onMembersChange(newMembers);
    };

    const handleAdminToggle = (user_uid_to_toggle) => {
        const newMembers = currentMembers.map(m =>
            m.user_uid === user_uid_to_toggle ? {...m, is_group_admin: !m.is_group_admin} : m
        );
        setCurrentMembers(newMembers);
        onMembersChange(newMembers);
    };

    return (
        <Box>
            <Typography variant="subtitle1" sx={{mt: 2, mb: 1}}>{memberTypeLabel}:</Typography>
            <TextField
                fullWidth
                variant="outlined"
                label={"Search for " + searchTypes.join(' or ') + " to add..."}
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                slotProps={{
                    input: { endAdornment: loading ? <CircularProgress size={20}/> : null },
                    htmlInput: { 'data-testid': 'member-search-input' },
                }}
            />
            {searchResults.length > 0 && (
                <Paper sx={{maxHeight: 150, overflow: 'auto', mt: 1}}>
                    <List dense data-testid="member-search-results">
                        {searchResults.map(user => (
                            <ListItem
                                key={user.id}
                                data-testid={`member-search-result-${user.id}`}
                                secondaryAction={
                                    <IconButton edge="end" aria-label="add" onClick={() => handleAddMember(user)}
                                                data-testid={`member-add-${user.id}`}>
                                        <AddCircleOutlineIcon color="primary"/>
                                    </IconButton>
                                }
                            >
                                <ListItemText primary={user.display_name}/>
                            </ListItem>
                        ))}
                    </List>
                </Paper>
            )}

            <Paper sx={{maxHeight: 200, overflow: 'auto', mt: 2, p: 1}} variant="outlined">
                {currentMembers.length === 0 ? (
                    <Typography sx={{p: 2, textAlign: 'center', color: 'text.secondary'}}>No users or groups
                        added.</Typography>
                ) : (
                    <List dense>
                        {currentMembers.map(member => (
                            <ListItem
                                key={member.user_uid}
                                data-testid={`member-row-${member.user_uid}`}
                                secondaryAction={
                                    <IconButton edge="end" aria-label="remove"
                                                onClick={() => handleRemoveMember(member.user_uid)}
                                                data-testid={`member-remove-${member.user_uid}`}>
                                        <RemoveCircleOutlineIcon color="error"/>
                                    </IconButton>
                                }
                            >
                                <ListItemText
                                    primary={member.user_uid}
                                    secondary={
                                        <FormControlLabel
                                            control={<Switch checked={member.is_group_admin}
                                                             onChange={() => handleAdminToggle(member.user_uid)}
                                                             size="small"
                                                             slotProps={{ input: { 'data-testid': `member-toggle-${member.user_uid}` } }}/>}
                                            label={<Typography variant="caption">{adminToggleLabel}</Typography>}
                                        />
                                    }
                                />
                            </ListItem>
                        ))}
                    </List>
                )}
            </Paper>
        </Box>
    );
}

export default UserSearchAndManage;