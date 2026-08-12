import React from 'react';
import {
    Box,
    Button,
    Typography,
    Paper,
    IconButton,
    TableContainer,
    Table,
    TableHead,
    TableBody,
    TableRow,
    TableCell,
    Tooltip
} from '@mui/material';
import AddIcon from "@mui/icons-material/Add";
import EditIcon from "@mui/icons-material/Edit";
import DeleteIcon from "@mui/icons-material/Delete";

// Helper to format date
const formatDate = (isoString) => {
    if (!isoString) return 'N/A';
    try {
        return new Date(isoString).toLocaleString();
    } catch (e) {
        return 'Invalid Date';
    }
};

function AdminProjectList({projects, onAddProject, onEditProject, onDeleteProject}) {
    if (!projects || projects.length === 0) {
        return (
            <Box>
                <Button variant="contained" startIcon={<AddIcon/>} onClick={onAddProject} size="small" sx={{mb: 2}}>
                    Add Project
                </Button>
                <Typography sx={{textAlign: 'center', mt: 3, p: 2, color: 'text.secondary'}}>No projects
                    found.</Typography>
            </Box>
        );
    }

    return (
        <>
            <Box sx={{display: 'flex', justifyContent: 'flex-end', mb: 1}}>
                <Button variant="contained" startIcon={<AddIcon/>} onClick={onAddProject} size="small">
                    Add Project
                </Button>
            </Box>
            <TableContainer component={Paper}>
                <Table stickyHeader size="small" aria-label="all projects table">
                    <TableHead>
                        <TableRow>
                            <TableCell sx={{fontWeight: 'bold'}}>ID</TableCell>
                            <TableCell sx={{fontWeight: 'bold'}}>Project Name</TableCell>
                            <TableCell sx={{fontWeight: 'bold'}}>Owner</TableCell>
                            <TableCell sx={{fontWeight: 'bold'}}>Created</TableCell>
                            <TableCell sx={{fontWeight: 'bold'}} align="right">Actions</TableCell>
                        </TableRow>
                    </TableHead>
                    <TableBody>
                        {projects.map((row) => (
                            <TableRow hover key={row.id}>
                                <TableCell>{row.id}</TableCell>
                                <TableCell>{row.name}</TableCell>
                                <TableCell>{row.owner_display}</TableCell>
                                <TableCell>{formatDate(row.created_at)}</TableCell>
                                <TableCell align="right">
                                    <Tooltip title="Edit Project">
                                        <IconButton size="small" color="primary" onClick={() => onEditProject(row)}>
                                            <EditIcon fontSize="small"/>
                                        </IconButton>
                                    </Tooltip>
                                    <Tooltip title="Delete Project">
                                        <IconButton size="small" color="error" onClick={() => onDeleteProject(row)}>
                                            <DeleteIcon fontSize="small"/>
                                        </IconButton>
                                    </Tooltip>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </TableContainer>
        </>
    );
}

export default AdminProjectList;