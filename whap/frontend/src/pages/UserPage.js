import React, { useState, useEffect, useCallback, useContext } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
    Box,
    Typography,
    CircularProgress,
    Alert,
    Button,
    Container,
    Tabs,
    Tab,
    Paper,
    Dialog,
    DialogTitle,
    DialogContent,
    DialogContentText,
    DialogActions
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ListAltIcon from '@mui/icons-material/ListAlt';
import FolderIcon from '@mui/icons-material/Folder';
import KeyIcon from '@mui/icons-material/Key';
import SupervisedUserCircleIcon from '@mui/icons-material/SupervisedUserCircle';
import AssessmentIcon from '@mui/icons-material/Assessment';

import api from '../services/api';
import { AuthContext } from '../contexts/AuthContext';

import ContainerForm from '../components/ContainerForm';
import ContainerDetails from '../components/ContainerDetail';
import ProjectList from '../components/ProjectList';
import SSHKeyList from '../components/SSHKeyList';
import UserGroupList from '../components/UserGroupList';
import ClusterStatistics from '../components/ClusterStatistics';
import Header from '../components/Header';

import ProjectModal from '../components/ProjectModal';
import SSHKeyCreateModal from '../components/SSHKeyCreateModal';
import UserGroupModal from '../components/UserGroupModal';

function UserPage() {
    const [searchParams, setSearchParams] = useSearchParams();
    const activeTab = searchParams.get('tab') || 'statistics';

    const [pageState, setPageState] = useState({
        containers: { data: [], loading: true, error: '' },
        projects: { data: [], loading: true, error: '' },
        sshKeys: { data: [], loading: true, error: '' },
        groups: { data: [], loading: true, error: '' },
    });

    // Modal States for user actions
    const [isProjectModalOpen, setIsProjectModalOpen] = useState(false);
    const [projectToEdit, setProjectToEdit] = useState(null);
    const [isKeyModalOpen, setIsKeyModalOpen] = useState(false);
    const [isGroupModalOpen, setIsGroupModalOpen] = useState(false);
    const [groupToEdit, setGroupToEdit] = useState(null);
    const [userPermissions, setUserPermissions] = useState(null);
    const [allServers, setAllServers] = useState([]);
    const [allImages, setAllImages] = useState([]);
    const [confirmDialog, setConfirmDialog] = useState({ isOpen: false, title: '', subTitle: '', onConfirm: () => { } });

    const { username, isAdmin, logout } = useContext(AuthContext);

    // --- Data Fetching Callbacks ---
    const fetchData = useCallback(async (type) => {
        setPageState(prev => ({ ...prev, [type]: { ...(prev[type] || {}), loading: true, error: '' } }));
        let endpoint;
        switch (type) {
            case 'containers':
                endpoint = '/api/containers';
                break;
            case 'projects':
                endpoint = '/api/projects';
                break;
            case 'sshKeys':
                endpoint = '/api/sshkeys';
                break;
            case 'groups':
                endpoint = '/api/groups';
                break;
            case 'create':
                return;
            case 'statistics':
                return;
            default:
                console.error("Unknown data type to fetch:", type);
                return;
        }

        try {
            const response = await api.get(endpoint);
            setPageState(prev => ({ ...prev, [type]: { data: response.data || [], loading: false, error: '' } }));
        } catch (err) {
            console.error(`Failed to fetch ${type}:`, err);
            const errorMessage = `Failed to load ${type}.`;
            setPageState(prev => ({
                ...prev,
                [type]: { ...(prev[type] || {}), data: prev[type]?.data || [], loading: false, error: errorMessage }
            }));
            if (err.response && err.response.status === 401 && logout) logout();
        }
    }, [logout]);


    // Effect to fetch data when tab changes (if not loaded)
    useEffect(() => {
        if (activeTab !== 'create' && activeTab !== 'statistics' && (!pageState[activeTab] || pageState[activeTab].data.length === 0)) {
            fetchData(activeTab);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeTab, fetchData]);


    useEffect(() => { // Initial data load
        const initialFetches = ['containers', 'projects', 'sshKeys', 'groups'];
        initialFetches.forEach(fetchData);

        const fetchModalData = async () => {
            try {
                const [permsRes, serversRes, imagesRes] = await Promise.all([
                    api.get('/api/permissions/my-permissions'),
                    api.get('/api/servers'),
                    api.get('/api/permissions/my-available-images'),
                ]);
                setUserPermissions(permsRes.data);
                setAllServers(serversRes.data);
                setAllImages(imagesRes.data);
            } catch (err) {
                console.error("Failed to load permissions or server list:", err);
            }
        };
        fetchModalData();
    }, [fetchData]);

    // --- Event Handlers ---
    const handleTabChange = (event, newValue) => {
        setSearchParams({ tab: newValue });
    };

    const handleContainerCreated = (newContainer) => {
        // Add to main list immediately
        setPageState(prev => ({
            ...prev,
            containers: {
                ...prev.containers,
                // Avoid duplicates if already added by a fast poll
                data: [newContainer, ...(prev.containers.data.filter(c => c.id !== newContainer.id) || [])]
            }
        }));
        setSearchParams({ tab: 'containers' }); // Switch to containers tab to see the new one provisioning
        fetchData('containers'); // Trigger polling check / immediate refresh
    };

    const handleContainerUpdate = (updatedContainer) => {
        setPageState(prev => ({
            ...prev,
            containers: {
                ...prev.containers,
                data: (prev.containers.data || []).map(c => c.id === updatedContainer.id ? updatedContainer : c)
            }
        }));
    };

    const handleContainerDelete = (deletedContainerId) => {
        setPageState(prev => ({
            ...prev,
            containers: {
                ...prev.containers,
                data: (prev.containers.data || []).filter(c => c.id !== deletedContainerId)
            }
        }));
    };

    // Project Modal Handlers
    const handleAddProject = () => {
        setProjectToEdit(null);
        setIsProjectModalOpen(true);
    };

    const handleEditProject = (project) => {
        setProjectToEdit(project);
        setIsProjectModalOpen(true);
    };

    const handleProjectSaved = () => {
        setIsProjectModalOpen(false);
        fetchData('projects');
    };

    const handleDeleteProject = (project) => {
        setConfirmDialog({
            isOpen: true,
            title: `Delete Project "${project.name}"?`,
            subTitle: "This action cannot be undone. The project's shared directory will also be queued for deletion.",
            onConfirm: async () => {
                try {
                    await api.delete(`/api/projects/${project.id}`);
                    fetchData('projects'); // Refresh list on success
                } catch (err) {
                    alert(err.response?.data?.message || 'Failed to delete project.');
                } finally {
                    setConfirmDialog({ ...confirmDialog, isOpen: false });
                }
            }
        });
    };

    // SSH Key Modal Handlers
    const handleKeyCreated = () => {
        setIsKeyModalOpen(false);
        fetchData('sshKeys');
    };

    const handleKeyDeleted = () => {
        setIsKeyModalOpen(false);
        fetchData('sshKeys');
    };

    // Group Modal Handlers
    const handleAddGroup = () => {
        setGroupToEdit(null); // Ensure we are in "create" mode
        setIsGroupModalOpen(true);
    };

    const handleEditGroup = async (group) => {
        try {
            // Fetch the full, detailed group object before editing
            const response = await api.get(`/api/groups/${group.id}`);
            setGroupToEdit(response.data);
            setIsGroupModalOpen(true);
        } catch (error) {
            console.error("Failed to fetch group details for editing:", error);
            // Optionally, show an error to the user
            alert("Could not load group details. Please try again.");
        }
    };

    const handleGroupSaved = () => {
        setIsGroupModalOpen(false);
        fetchData('groups'); // Refresh the list of groups
    };

    const handleDeleteGroup = (group) => {
        setConfirmDialog({
            isOpen: true,
            title: `Delete Group "${group.name}"?`,
            subTitle: "You are an admin of this group. Deleting it will remove it for all members and cannot be undone.",
            onConfirm: async () => {
                try {
                    await api.delete(`/api/groups/${group.id}`);
                    fetchData('groups'); // Refresh list on success
                } catch (err) {
                    alert(err.response?.data?.message || 'Failed to delete group.');
                } finally {
                    setConfirmDialog({ ...confirmDialog, isOpen: false });
                }
            }
        });
    };

    // --- Render Logic ---
    const renderCurrentTab = () => {
        const currentTabState = pageState[activeTab] || { data: [], loading: true, error: '' }; // Fallback for safety

        switch (activeTab) {
            case 'statistics':
                return <ClusterStatistics />;
            case 'containers':
                return (
                    <>
                        {currentTabState.error && <Alert severity="error" sx={{ mb: 2 }}>{currentTabState.error}</Alert>}
                        {currentTabState.loading && currentTabState.data.length === 0 ? (
                            <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}><CircularProgress /></Box>
                        ) : currentTabState.data.length > 0 ? (
                            currentTabState.data.map((container) => (
                                <ContainerDetails
                                    key={container.id}
                                    container={container}
                                    onUpdate={handleContainerUpdate}
                                    onDelete={handleContainerDelete}
                                />
                            ))
                        ) : (
                            !currentTabState.loading &&
                            <Typography sx={{ textAlign: 'center', mt: 3, color: 'text.secondary' }}>No active containers
                                found.</Typography>
                        )}
                        <Button onClick={() => fetchData('containers', false)} sx={{ mt: 2 }}
                            disabled={currentTabState.loading && currentTabState.data.length > 0}>Refresh
                            List</Button>
                    </>
                );
            case 'create':
                return <ContainerForm onContainerCreated={handleContainerCreated} />;
            case 'projects':
                return <ProjectList projects={pageState.projects.data}
                    onAddProject={handleAddProject}
                    onEditProject={handleEditProject}
                    onDeleteProject={handleDeleteProject}
                    isLoading={pageState.projects.loading}
                    error={pageState.projects.error} />;
            case 'sshKeys':
                return <SSHKeyList sshKeys={pageState.sshKeys.data}
                    onAddKey={() => setIsKeyModalOpen(true)}
                    refreshKeys={handleKeyDeleted}
                    isLoading={pageState.sshKeys.loading}
                    error={pageState.sshKeys.error} />;
            case 'groups':
                return <UserGroupList groups={pageState.groups.data}
                    onAddGroup={handleAddGroup}
                    onEditGroup={handleEditGroup}
                    onDeleteGroup={handleDeleteGroup}
                    isLoading={pageState.groups.loading}
                    error={pageState.groups.error} />;
            default:
                return <Typography>Select a tab.</Typography>;
        }
    };

    return (
        <>
            <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
                <Header title="User Panel" />

                <Paper>
                    <Box sx={{ display: 'flex', justifyContent: 'center' }}>
                        <Tabs value={activeTab} onChange={handleTabChange} variant="scrollable"
                            scrollButtons="auto">
                            <Tab label="Statistics" value="statistics" icon={<AssessmentIcon />} iconPosition="start" />
                            <Tab label="My Containers" value="containers" icon={<ListAltIcon />} iconPosition="start" />
                            <Tab label="Create Container" value="create" icon={<AddIcon />} iconPosition="start" />
                            <Tab label="My Projects" value="projects" icon={<FolderIcon />} iconPosition="start" />
                            <Tab label="My Groups" value="groups" icon={<SupervisedUserCircleIcon />}
                                iconPosition="start" />
                            <Tab label="My SSH Keys" value="sshKeys" icon={<KeyIcon />} iconPosition="start" />
                        </Tabs>
                    </Box>
                </Paper>

                <Box sx={{ mt: 3 }}>
                    {renderCurrentTab()}
                </Box>
            </Container>

            {/* Modals for user actions */}
            <ProjectModal
                open={isProjectModalOpen}
                onClose={() => setIsProjectModalOpen(false)}
                onProjectSaved={handleProjectSaved}
                projectToEdit={projectToEdit}
            />
            <SSHKeyCreateModal
                open={isKeyModalOpen}
                onClose={() => setIsKeyModalOpen(false)}
                onKeyCreated={handleKeyCreated}
            />
            <UserGroupModal
                open={isGroupModalOpen}
                onClose={() => setIsGroupModalOpen(false)}
                onGroupSaved={handleGroupSaved}
                groupToEdit={groupToEdit}
                userPermissions={userPermissions}
                allServers={allServers}
                allImages={allImages}
            />

            {/* Confirmation Dialog for Deletions */}
            <Dialog open={confirmDialog.isOpen} onClose={() => setConfirmDialog({ ...confirmDialog, isOpen: false })}>
                <DialogTitle>{confirmDialog.title}</DialogTitle>
                <DialogContent>
                    <DialogContentText>{confirmDialog.subTitle}</DialogContentText>
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setConfirmDialog({ ...confirmDialog, isOpen: false })}>Cancel</Button>
                    <Button onClick={confirmDialog.onConfirm} color="error" autoFocus>
                        Delete
                    </Button>
                </DialogActions>
            </Dialog>
        </>
    );
}

export default UserPage;