import React, { useState, useEffect, useCallback, useContext } from 'react';
import {
    Box,
    Typography,
    CircularProgress,
    Alert,
    Container,
    Paper,
    Tabs,
    Tab,
    Dialog,
    DialogTitle,
    DialogContent,
    DialogContentText,
    DialogActions,
    Button,
} from '@mui/material';
import { Link as RouterLink, useSearchParams } from 'react-router-dom';

// Icons
import ComputerIcon from '@mui/icons-material/Computer'; // Icon for Servers tab
import GroupIcon from '@mui/icons-material/Group'; // Icon for Users tab
import VpnKeyIcon from '@mui/icons-material/VpnKey'; // Icon for SSH keys
import FolderIcon from '@mui/icons-material/Folder'; // Icon for Projects tab
import ListAltIcon from '@mui/icons-material/ListAlt'; // Icon for Containers tab
import SettingsEthernetIcon from '@mui/icons-material/SettingsEthernet'; // Icon for IP addresses tab
import LanguageIcon from '@mui/icons-material/Language';  // Icon for networks tab
import SupervisedUserCircleIcon from '@mui/icons-material/SupervisedUserCircle'; // Icon for Groups

// API and Context
import api from '../services/api';
import { AuthContext } from "../contexts/AuthContext";

// Child Components
import AdminContainerList from '../components/AdminContainerList';
import AdminProjectList from '../components/AdminProjectList';
import ComputeServerList from '../components/ComputeServerList';
import StaticAddressList from '../components/StaticAddressList';
import NetworkList from "../components/NetworkList";
import LocalUserList from '../components/LocalUserList';
import AdminSSHKeyList from "../components/AdminSSHKeyList";
import AdminGroupList from "../components/AdminGroupList";
import Header from '../components/Header';

// Modals
import ComputeServerModal from '../components/ComputeServerModal';
import StaticAddressModal from '../components/StaticAddressModal';
import NetworkModal from "../components/NetworkModal";
import LocalUserModal from '../components/LocalUserModal';
import AdminContainerModal from "../components/AdminContainerModal";
import AdminProjectModal from "../components/AdminProjectModal";
import AdminSSHKeyModal from "../components/AdminSSHKeyModal";
import AdminGroupModal from "../components/AdminGroupModal";

function AdminPage() {
    const { username, logout } = useContext(AuthContext);
    const [searchParams, setSearchParams] = useSearchParams();
    const activeTab = searchParams.get('tab') || 'containers';

    const [pageState, setPageState] = useState({
        containers: { data: [], loading: true, error: '' },
        projects: { data: [], loading: true, error: '' },
        users: { data: [], loading: true, error: '' },
        servers: { data: [], loading: true, error: '' },
        addresses: { data: [], loading: true, error: '' },
        networks: { data: [], loading: true, error: '' },
        images: { data: [], loading: true, error: '' },
        allSshKeys: { data: [], loading: true, error: '' },
        groups: { data: [], loading: true, error: '' },
    });

    // --- Unified Modal State Management ---
    const [modalState, setModalState] = useState({
        user: { open: false, item: null },
        server: { open: false, item: null },
        network: { open: false, item: null },
        address: { open: false, item: null },
        container: { open: false, item: null },
        project: { open: false, item: null },
        sshKey: { open: false, item: null },
        group: { open: false, item: null },
        deleteConfirm: { open: false, item: null, type: '', message: '' },
    });
    const [modalLoading, setModalLoading] = useState(false);
    const [modalError, setModalError] = useState('');
    const [stoppingContainerId, setStoppingContainerId] = useState(null);

    // --- Data Fetching ---
    const fetchData = useCallback(async (type) => {
        // Correctly map the API endpoint type to the state key
        const stateKey = type === 'sshkeys' ? 'allSshKeys' : type;
        setPageState(prev => ({ ...prev, [stateKey]: { ...(prev[stateKey] || {}), loading: true, error: '' } }));
        try {
            let endpoint = `/api/admin/${type}`;
            if (type === 'servers') {
                endpoint = '/api/servers';
            } else if (type === 'addresses' || type === 'static_addresses') {
                endpoint = '/api/admin/static_addresses';
            } else if (type === 'images') {
                endpoint = '/api/images';
            } else if (type === 'allSshKeys') {
                endpoint = '/api/admin/sshkeys';
            } else {
                endpoint = `/api/admin/${type}`;
            }
            const response = await api.get(endpoint);
            setPageState(prev => ({ ...prev, [stateKey]: { data: response.data || [], loading: false, error: '' } }));
        } catch (err) {
            console.error(`Failed to fetch admin data for ${type}:`, err);
            setPageState(prev => ({ ...prev, [stateKey]: { data: [], loading: false, error: `Failed to load ${type}.` } }));
            if (err.response?.status === 401) logout();
        }
    }, [logout]);

    useEffect(() => {
        fetchData(activeTab === 'sshKeys' ? 'allSshKeys' : activeTab);
    }, [activeTab, fetchData]);

    // --- Generic Modal and Action Handlers ---
    const handleTabChange = (event, newValue) => {
        setSearchParams({ tab: newValue });
    }

    const openModal = async (type, item = null) => {
        setModalError('');
        if (type === 'group' && item) {
            // For editing a group, first fetch its full details including members
            try {
                const response = await api.get(`/api/admin/groups/${item.id}`);
                setModalState(prev => ({ ...prev, [type]: { open: true, item: response.data } }));
            } catch (err) {
                setModalError('Failed to load group details.');
            }
        } else {
            setModalState(prev => ({ ...prev, [type]: { open: true, item: item } }));
        }
    };

    const closeModal = (type) => {
        setModalState(prev => ({ ...prev, [type]: { open: false, item: null } }));
    };

    const createSaveHandler = (modalKey, endpoint) => async (payload, isEdit, itemId, clientSideError) => {
        if (clientSideError) {
            setModalError(clientSideError);
            return;
        }
        setModalLoading(true);
        setModalError('');
        try {
            let apiEndpoint = `/api/admin/${endpoint}`;
            if (endpoint === 'servers') { // Handle non-admin endpoint for servers
                apiEndpoint = `/api/servers`;
            }

            if (isEdit) {
                await api.put(`${apiEndpoint}/${itemId}`, payload);
            } else {
                await api.post(apiEndpoint, payload);
            }
            closeModal(modalKey);
            fetchData(endpoint);
            if (endpoint === 'networks') fetchData('addresses');
        } catch (err) {
            console.error(`Failed to save ${modalKey}:`, err);
            setModalError(err.response?.data?.message || `Failed to save item.`);
        } finally {
            setModalLoading(false);
        }
    };

    const handleSaveContainer = createSaveHandler('container', 'containers');
    const handleSaveProject = createSaveHandler('project', 'projects');
    const handleSaveSshKey = createSaveHandler('sshKey', 'sshkeys');
    const handleSaveUser = createSaveHandler('user', 'users');
    const handleSaveServer = createSaveHandler('server', 'servers');
    const handleSaveNetwork = createSaveHandler('network', 'networks');
    const handleSaveAddress = createSaveHandler('address', 'static_addresses');
    const handleSaveGroup = createSaveHandler('group', 'groups');

    const openDeleteConfirm = (item, type, message = null) => {
        const itemIdentifier = item?.name || item?.username || item?.ip_address;
        const defaultMessage = `Are you sure you want to delete the ${type.replace('_', ' ')}: "${itemIdentifier}"? This action cannot be undone.`;
        setModalState(prev => ({
            ...prev,
            deleteConfirm: { open: true, item: item, type: type, message: message || defaultMessage }
        }));
        setModalError('');
    };

    const handleDelete = async () => {
        const { item, type } = modalState.deleteConfirm;
        if (!item || !type) return;

        setModalLoading(true);
        setModalError('');
        try {
            await api.delete(`/api/admin/${type}/${item.id}`);
            closeModal('deleteConfirm');
            fetchData(type);
        } catch (err) {
            console.error(`Failed to delete ${type}:`, err);
            setModalError(err.response?.data?.message || `Failed to delete item.`);
        } finally {
            setModalLoading(false);
        }
    };

    const handleFreeAddress = async (address) => {
        if (!window.confirm(`Are you sure you want to free the IP address ${address.ip_address} from its assigned container? This might affect a running container.`)) {
            return;
        }

        setModalLoading(true); // Reuse existing loading state for feedback
        setModalError('');
        try {
            await api.post(`/api/admin/static_addresses/${address.id}/free`);
            fetchData('addresses'); // Refresh the list to show the change
        } catch (err) {
            console.error(`Failed to free address:`, err);
            // Display the error in a prominent place, e.g., an alert or a modal
            alert(err.response?.data?.message || 'An unexpected error occurred.');
        } finally {
            setModalLoading(false);
        }
    };

    const handleAdminStopContainer = async (containerId) => {
        setStoppingContainerId(containerId);
        try {
            await api.post(`/api/containers/${containerId}/stop`);
            setTimeout(() => fetchData('containers'), 3000);
        } catch (err) {
            alert(`Failed to send stop command: ${err.response?.data?.message || err.message}`);
        } finally {
            setStoppingContainerId(null);
        }
    };

    const handleAdminDeleteContainerDB = (container) => {
        const message = <>
            Are you sure you want to delete the database record for container ID {container.id}? <br /><br />
            <Typography variant="caption" color="error">
                Warning: This only removes the record and releases its IP.
                It does **not** stop the actual running container.
            </Typography>
        </>;
        openDeleteConfirm(container, 'containers', message);
    };

    // --- Rendering Logic ---
    const renderContent = () => {
        const state = pageState[activeTab];
        if (!state) return null;

        if (state.loading) return <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}><CircularProgress /></Box>;
        if (state.error) return <Alert severity="error" sx={{ m: 2 }}>{state.error}</Alert>;

        // Render specific list components
        switch (activeTab) {
            case 'containers':
                return <AdminContainerList containers={state.data}
                    onStop={handleAdminStopContainer}
                    onDelete={handleAdminDeleteContainerDB}
                    onAddContainer={() => openModal('container')}
                    onEditContainer={(item) => openModal('container', item)}
                    stoppingContainerId={stoppingContainerId} />;
            case 'projects':
                return <AdminProjectList projects={state.data}
                    onAddProject={() => openModal('project')}
                    onEditProject={(item) => openModal('project', item)}
                    onDeleteProject={(item) => openDeleteConfirm(item, 'projects')} />;
            case 'users':
                return <LocalUserList users={state.data}
                    onAddUser={() => openModal('user')}
                    onEditUser={(item) => openModal('user', item)}
                    onDeleteUser={(item) => openDeleteConfirm(item, 'users')} />;
            case 'groups':
                return <AdminGroupList groups={state.data}
                    onAddGroup={() => openModal('group')}
                    onEditGroup={(item) => openModal('group', item)}
                    onDeleteGroup={(item) => openDeleteConfirm(item, 'groups')} />;
            case 'allSshKeys':
                return <AdminSSHKeyList sshKeys={state.data}
                    onAddKey={() => openModal('sshKey')}
                    onEditKey={(item) => openModal('sshKey', item)}
                    onDeleteKey={(item) => openDeleteConfirm(item, 'sshkeys')} />;
            case 'servers':
                return <ComputeServerList servers={state.data}
                    onAddServer={() => openModal('server')}
                    onEditServer={(item) => openModal('server', item)}
                    onDeleteServer={(item) => openDeleteConfirm(item, 'servers')} />;
            case 'networks':
                return <NetworkList networks={state.data}
                    onAdd={() => openModal('network')}
                    onEdit={(item) => openModal('network', item)}
                    onDelete={(item) => openDeleteConfirm(item, 'networks')} />;
            case 'addresses':
                return <StaticAddressList addresses={state.data}
                    servers={pageState.servers.data}
                    onAddAddress={() => openModal('address')}
                    onEditAddress={(item) => openModal('address', item)}
                    onDeleteAddress={(item) => openDeleteConfirm(item, 'static_addresses')}
                    onFreeAddress={handleFreeAddress} />;
            default:
                return <Typography sx={{ textAlign: 'center', mt: 3, p: 2, color: 'text.secondary' }}>
                    No content for this tab.
                </Typography>;
        }
    };

    return (
        <>
            <Container maxWidth="xl" sx={{ mt: 4, mb: 4 }}>
                <Header title="Admin Panel" />

                <Paper>
                    <Box sx={{ display: 'flex', justifyContent: 'center' }}>
                        <Tabs value={activeTab} onChange={handleTabChange} variant="scrollable"
                            scrollButtons="auto">
                            <Tab label="All Containers" value="containers" icon={<ListAltIcon />} iconPosition="start" />
                            <Tab label="All Projects" value="projects" icon={<FolderIcon />} iconPosition="start" />
                            <Tab label="Local Users" value="users" icon={<GroupIcon />} iconPosition="start" />
                            <Tab label="Groups" value="groups" icon={<SupervisedUserCircleIcon />} iconPosition="start" />
                            <Tab label="All SSH Keys" value="allSshKeys" icon={<VpnKeyIcon />} iconPosition="start" />
                            <Tab label="Compute Servers" value="servers" icon={<ComputerIcon />} iconPosition="start" />
                            <Tab label="Networks" value="networks" icon={<LanguageIcon />} iconPosition="start" />
                            <Tab label="Static Addresses" value="addresses" icon={<SettingsEthernetIcon />}
                                iconPosition="start" />
                        </Tabs>
                    </Box>
                </Paper>

                <Box sx={{ mt: 3 }}>
                    {renderContent()}
                </Box>
            </Container>

            {/* Modals */}
            <AdminProjectModal
                open={modalState.project.open}
                onClose={() => closeModal('project')}
                onSave={handleSaveProject}
                projectToEdit={modalState.project.item}
                allLocalUsers={pageState.users.data}
                allGroups={pageState.groups.data}
                loading={modalLoading}
                error={modalError}
            />
            <AdminContainerModal
                open={modalState.container.open}
                onClose={() => closeModal('container')}
                onSave={handleSaveContainer}
                containerToEdit={modalState.container.item}
                allProjects={pageState.projects.data}
                allServers={pageState.servers.data}
                allImages={pageState.images.data}
                allSshKeys={pageState.allSshKeys.data}
                allStaticAddresses={pageState.addresses.data}
                allLocalUsers={pageState.users.data}
                loading={modalLoading}
                error={modalError}
            />
            <LocalUserModal
                open={modalState.user.open}
                onClose={() => closeModal('user')}
                onSave={handleSaveUser}
                userToEdit={modalState.user.item}
                loading={modalLoading}
                error={modalError}
            />
            <AdminGroupModal
                open={modalState.group.open}
                onClose={() => closeModal('group')}
                onSave={handleSaveGroup}
                groupToEdit={modalState.group.item}
                allServers={pageState.servers.data}
                allImages={pageState.images.data}
                loading={modalLoading}
                error={modalError}
            />
            <AdminSSHKeyModal
                open={modalState.sshKey.open}
                onClose={() => closeModal('sshKey')}
                onSave={handleSaveSshKey}
                keyToEdit={modalState.sshKey.item}
                allLocalUsers={pageState.users.data}
                loading={modalLoading}
                error={modalError}
            />
            <ComputeServerModal
                open={modalState.server.open}
                onClose={() => closeModal('server')}
                onSave={handleSaveServer}
                serverToEdit={modalState.server.item}
                loading={modalLoading}
                error={modalError}
            />
            <NetworkModal
                open={modalState.network.open}
                onClose={() => closeModal('network')}
                onSave={handleSaveNetwork}
                networkToEdit={modalState.network.item}
                loading={modalLoading}
                error={modalError}
            />
            <StaticAddressModal
                open={modalState.address.open}
                onClose={() => closeModal('address')}
                onSave={handleSaveAddress}
                addressToEdit={modalState.address.item}
                allServers={pageState.servers.data}
                allNetworks={pageState.networks.data}
                loading={modalLoading}
                error={modalError}
            />

            {/* Generic Delete Confirmation Dialog */}
            <Dialog open={modalState.deleteConfirm.open} onClose={() => closeModal('deleteConfirm')}>
                <DialogTitle>Confirm Deletion</DialogTitle>
                <DialogContent>
                    <DialogContentText>{modalState.deleteConfirm.message}</DialogContentText>
                    {modalError && <Alert severity="error" sx={{ mt: 2 }}>{modalError}</Alert>}
                </DialogContent>
                <DialogActions sx={{ position: 'relative' }}>
                    <Button onClick={() => closeModal('deleteConfirm')} disabled={modalLoading}>Cancel</Button>
                    <Button onClick={handleDelete} color="error" autoFocus
                        disabled={modalLoading}> Delete {modalLoading && <CircularProgress size={20} sx={{
                            position: 'absolute',
                            top: '50%',
                            left: '50%',
                            mt: '-10px',
                            ml: '-10px'
                        }} />} </Button>
                </DialogActions>
            </Dialog>
        </>
    );
}

export default AdminPage;