import React from 'react';
import {
    Box,
    Typography,
    List,
    ListItem,
    ListItemText,
    Paper,
    Button,
    CircularProgress,
    Alert,
    Tooltip,
    IconButton
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import FolderIcon from '@mui/icons-material/Folder';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';

// Helper to format date
const formatDate = (isoString) => {
    if (!isoString) return 'N/A';
    try {
        return new Date(isoString).toLocaleString();
    } catch (e) {
        return 'Invalid Date';
    }
};

function ProjectList({projects, onAddProject, onEditProject, onDeleteProject, isLoading, error}) {

    if (isLoading) {
        return <Box sx={{display: 'flex', justifyContent: 'center', p: 3}}><CircularProgress/></Box>;
    }

    return (
        <Paper elevation={2} sx={{p: 2}}>
            <Box sx={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2}}>
                <Typography variant="h6">My Projects</Typography>
                <Button
                    variant="contained"
                    startIcon={<AddIcon/>}
                    onClick={onAddProject}
                    size="small"
                >
                    New Project
                </Button>
            </Box>
            {error && <Alert severity="error" sx={{mb: 2}}>{error}</Alert>}
            {projects && projects.length > 0 ? (
                <List dense>
                    {projects.map((project) => (
                        <ListItem key={project.id} secondaryAction={
                            <>
                                <Typography variant="caption" color="textSecondary" sx={{mr: 2}}>
                                    Created: {formatDate(project.created_at)}
                                </Typography>
                                <Tooltip title="Edit Project & Shares">
                                    <IconButton edge="end" aria-label="edit" onClick={() => onEditProject(project)}>
                                        <EditIcon/>
                                    </IconButton>
                                </Tooltip>
                                <Tooltip title="Delete Project">
                                    <IconButton edge="end" aria-label="delete" onClick={() => onDeleteProject(project)} sx={{ ml: 1 }}>
                                        <DeleteIcon color="error" />
                                    </IconButton>
                                </Tooltip>
                            </>
                        }>
                            <FolderIcon sx={{mr: 1.5, color: 'action.active'}}/>
                            <ListItemText
                                primary={project.name}
                                // secondary={`Owner: ${project.owner_display}`} // Can add owner if needed
                            />
                        </ListItem>
                    ))}
                </List>
            ) : (
                <Typography sx={{textAlign: 'center', mt: 3, color: 'text.secondary'}}>
                    You haven't created any projects yet.
                </Typography>
            )}
        </Paper>
    );
}

export default ProjectList;