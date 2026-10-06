import React, {
    useState,
    useEffect,
    useContext,
    useCallback,
    useMemo
} from 'react';
import {
    Box,
    Button,
    TextField,
    Select,
    MenuItem,
    FormControl,
    InputLabel,
    Grid,
    CircularProgress,
    Typography,
    FormGroup,
    FormControlLabel,
    Checkbox,
    Paper,
    FormHelperText,
    Alert,
    IconButton,
    Stack,
    List,
    ListItem,
    Chip,
    Switch,
    Tooltip,
    Dialog,
    DialogTitle,
    DialogContent,
    DialogActions
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from "@mui/icons-material/Delete";
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import InfoIcon from '@mui/icons-material/Info';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import LayersIcon from '@mui/icons-material/Layers';
import VpnKeyIcon from '@mui/icons-material/VpnKey';
import StorageIcon from '@mui/icons-material/Storage';
import DnsIcon from '@mui/icons-material/Dns';
import SpeedIcon from '@mui/icons-material/Speed';
import DeveloperBoardIcon from '@mui/icons-material/DeveloperBoard';
import api from '../services/api';
import { AuthContext } from '../contexts/AuthContext';
import ProjectModal from './ProjectModal';

function ContainerForm({ onContainerCreated }) {
    const getFutureDateString = (months) => {
        const date = new Date();
        date.setMonth(date.getMonth() + months);
        return date.toISOString().split('T')[0]; // Format as YYYY-MM-DD
    };

    // --- State ---
    const [formData, setFormData] = useState({
        projectId: '',
        serverId: '',
        imageId: '',
        sshKeyId: '',
        gpus: [],
        password: '',
        cpuLimit: 'unlimited',
        ttlDate: getFutureDateString(3),
    });
    const [projects, setProjects] = useState([]);
    const [servers, setServers] = useState([]);
    const [images, setImages] = useState([]);
    const [sshKeys, setSshKeys] = useState([]);
    const [availableShares, setAvailableShares] = useState([]);
    const [mountedShares, setMountedShares] = useState([]);
    const [shareToMount, setShareToMount] = useState('');
    const [allNetworks, setAllNetworks] = useState([]);
    const [allAddresses, setAllAddresses] = useState([]);
    const [requestPublicIp, setRequestPublicIp] = useState(false);

    const [loadingOptions, setLoadingOptions] = useState({ // Individual loading states
        projects: true,
        servers: true,
        images: true,
        keys: true,
        shares: true,
        networks: true,
        addresses: true,
    });
    const [error, setError] = useState('');
    const [loadingSubmit, setLoadingSubmit] = useState(false);
    const { user } = useContext(AuthContext);
    const [isProjectModalOpen, setIsProjectModalOpen] = useState(false);
    const [isVolumeDialogOpen, setIsVolumeDialogOpen] = useState(false);

    const selectedImage = useMemo(() =>
        images.find(i => i.id === formData.imageId),
        [images, formData.imageId]);

    const ttlConfig = useMemo(() => {
        const imageName = selectedImage?.name || '';
        const isLocal = imageName.startsWith('local_');
        const isSynced = imageName.startsWith('synced_');

        return {
            // Synced images hide the TTL. Local images force it.
            isVisible: isLocal,
            isRequired: isLocal,
            maxDate: getFutureDateString(12), // Max 12 months
            minDate: new Date().toISOString().split('T')[0] // Today
        };
    }, [selectedImage]);

    // Effect: Ensure valid TTL when image changes
    useEffect(() => {
        if (ttlConfig.isRequired && !formData.ttlDate) {
            // If user switched to a local image and date was empty, reset to default
            setFormData(prev => ({ ...prev, ttlDate: getFutureDateString(3) }));
        }
    }, [ttlConfig.isRequired, formData.ttlDate]);

    // --- Data Fetching ---
    const fetchProjects = useCallback(async () => {
        setLoadingOptions(prev => ({ ...prev, projects: true }));
        try {
            const res = await api.get('/api/projects');
            setProjects(res.data || []);
            setLoadingOptions(prev => ({ ...prev, projects: false }));
            return res.data || [];
        } catch (err) {
            console.error("Failed to load projects:", err);
            setError(prev => prev + ' Failed to load projects.');
            setProjects([]);
            setLoadingOptions(prev => ({ ...prev, projects: false }));
            return [];
        }
    }, []);

    // Separate function to fetch SSH Keys for clarity and debugging
    const fetchSSHKeys = useCallback(async () => {
        setLoadingOptions(prev => ({ ...prev, keys: true }));
        try {
            const res = await api.get('/api/sshkeys');
            setSshKeys(res.data || []); // Update state
        } catch (err) {
            console.error("Failed to load SSH keys:", err);
            setError(prev => prev + ' Failed to load SSH keys.');
            setSshKeys([]); // Clear on error
        } finally {
            setLoadingOptions(prev => ({ ...prev, keys: false }));
        }
    }, []);

    // Fetch static data (servers, images) and initial dynamic data
    useEffect(() => {
        const fetchStaticOptions = async () => {
            setLoadingOptions(prev => ({ ...prev, servers: true, images: true, shares: true }));
            try {
                const [
                    serversRes,
                    imagesRes,
                    sharesRes,
                    networksRes,
                    addressesRes] = await Promise.all([
                        api.get('/api/permissions/my-available-servers'),
                        api.get('/api/permissions/my-available-images'),
                        api.get('/api/shared-volumes'),
                        api.get('/api/my-networks'),
                        api.get('/api/my-static_addresses')
                    ]);
                setServers(serversRes.data || []);
                setImages(imagesRes.data || []);
                setAvailableShares(sharesRes.data || []);
                setAllNetworks(networksRes.data || []);
                setAllAddresses(addressesRes.data || []);
                // Pre-selection logic
                if (serversRes.data?.length === 1) setFormData(prev => ({ ...prev, serverId: serversRes.data[0].id }));
                if (imagesRes.data?.length === 1) setFormData(prev => ({ ...prev, imageId: imagesRes.data[0].id }));
            } catch (err) {
                console.error("Failed to load static options:", err);
                setError('Failed to load server/image options.');
            } finally {
                setLoadingOptions(prev => ({ ...prev, servers: false, images: false, shares: false }));
            }
        };

        fetchStaticOptions();
        fetchProjects(); // Fetch projects
        fetchSSHKeys(); // Fetch SSH keys separately

    }, [fetchProjects, fetchSSHKeys]); // Include fetch callbacks in dependency array

    // Find the full server object based on the selected ID
    const selectedServer = useMemo(() =>
        servers.find(s => s.id === formData.serverId),
        [formData.serverId, servers]
    );

    // Create the array of GPU options based on the selected server
    const gpuOptions = useMemo(() =>
        selectedServer ? Array.from({ length: selectedServer.gpu_count }, (_, i) => String(i)) : [],
        [selectedServer]
    );

    // Every installed GPU is shown; those the user's groups don't include are
    // disabled. The server enforces the same list, so a backend that doesn't
    // send it yet just means nothing is greyed out.
    const allowedGpus = useMemo(() =>
        selectedServer?.allowed_gpus ?? gpuOptions,
        [selectedServer, gpuOptions]
    );

    const publicIpConfig = useMemo(() => {
        if (!formData.serverId || allAddresses.length === 0 || allNetworks.length === 0) {
            return { isVisible: false, isDisabled: true, isForced: false, helperText: '' };
        }

        const serverAddresses = allAddresses.filter(addr =>
            addr.available_server_ids.includes(formData.serverId)
        );

        const publicNetworks = new Set(
            allNetworks.filter(net => net.name.endsWith('public')).map(net => net.id)
        );

        const publicAddresses = serverAddresses.filter(addr => publicNetworks.has(addr.network_id));
        const privateAddresses = serverAddresses.filter(addr => !publicNetworks.has(addr.network_id));

        const hasFreePublicIp = publicAddresses.some(addr => !addr.assigned_container_id);

        const isVisible = publicAddresses.length > 0;
        if (!isVisible) {
            return { isVisible: false, isDisabled: true, isForced: false, helperText: '' };
        }

        const isForced = privateAddresses.length === 0;
        const isDisabled = isForced || !hasFreePublicIp;
        let helperText = '';
        if (isForced) {
            helperText = 'Only public IPs are available for this server.';
        } else if (isDisabled) {
            helperText = 'No free public IPs are currently available.';
        }

        return { isVisible, isDisabled, isForced, helperText };

    }, [formData.serverId, allAddresses, allNetworks]);

    useEffect(() => {
        if (publicIpConfig.isForced) {
            setRequestPublicIp(true);
        } else {
            setRequestPublicIp(false);
        }
    }, [publicIpConfig.isForced]);

    // Filter available shares to remove the currently selected main project
    const filteredAvailableShares = useMemo(() => {
        if (!formData.projectId) {
            return availableShares;
        }
        const selectedProject = projects.find(p => p.id === formData.projectId);
        if (!selectedProject) {
            return availableShares;
        }
        const ownProjectShareName = `My Project: ${selectedProject.name}`;
        return availableShares.filter(share => share.name !== ownProjectShareName);
    }, [availableShares, formData.projectId, projects]);

    // Effect to reset GPU selection when the server changes
    useEffect(() => {
        // When serverId changes, reset the selected GPUs
        setFormData(prev => ({ ...prev, gpus: [] }));
    }, [formData.serverId]);

    // Handler for project creation
    const handleProjectCreatedInForm = (newProject) => {
        setProjects(prev => [...prev, newProject].sort((a, b) => a.name.localeCompare(b.name)));
        setFormData(prev => ({ ...prev, projectId: newProject.id }));
        fetchProjects();
    };

    // --- Form Handlers ---
    const handleInputChange = (event) => {
        const { name, value } = event.target;
        setFormData(prev => ({ ...prev, [name]: value }));
    };

    const handleTtlQuickSelect = (months) => {
        setFormData(prev => ({ ...prev, ttlDate: getFutureDateString(months) }));
    };

    const handleCpuLimitQuickSelect = (limit) => {
        setFormData(prev => ({ ...prev, cpuLimit: limit }));
    };

    const handleGpuChange = (event) => {
        const { value, checked } = event.target;
        setFormData(prev => {
            const currentGpus = prev.gpus;
            if (checked) {
                return { ...prev, gpus: [...new Set([...currentGpus, value])].sort() };
            } else {
                return { ...prev, gpus: currentGpus.filter(gpu => gpu !== value) };
            }
        });
    };

    const handleAddShare = () => {
        const shareToAdd = availableShares.find(s => s.host_path === shareToMount);
        if (shareToAdd && !mountedShares.some(ms => ms.host_path === shareToAdd.host_path)) {
            // Sanitize the name for the default path
            const baseName = shareToAdd.name.replace(/^(My Project: |Shared: |Dataset: )/, '');
            const sanitizedName = baseName.replace(/[^a-zA-Z0-9_-]/g, '_');
            const defaultMountPath = `/home/${user.username}/${sanitizedName}`;

            setMountedShares(prev => [...prev, {
                ...shareToAdd,
                container_path: defaultMountPath,
                use_local_ssd: false // Default to false
            }]);
            setShareToMount('');
        }
    };

    const handleRemoveShare = (hostPath) => {
        setMountedShares(prev => prev.filter(s => s.host_path !== hostPath));
    };

    const handleSharePathChange = (hostPath, newContainerPath) => {
        setMountedShares(prev => prev.map(s => s.host_path === hostPath ? {
            ...s,
            container_path: newContainerPath
        } : s));
    };

    const handleToggleLocal = (hostPath) => {
        setMountedShares(prev => prev.map(s => s.host_path === hostPath ? {
            ...s,
            use_local_ssd: !s.use_local_ssd
        } : s));
    };

    const handleSubmit = async (event) => {
        event.preventDefault();
        setLoadingSubmit(true); // Use separate loading state
        setError('');
        if (ttlConfig.isVisible && ttlConfig.isRequired) {
            if (!formData.ttlDate) {
                setError("An Auto-Deletion (TTL) date is required for this image.");
                setLoadingSubmit(false);
                return;
            }
            const selectedDate = new Date(formData.ttlDate);
            const maxDate = new Date(ttlConfig.maxDate);
            if (selectedDate > maxDate) {
                setError(`TTL Date cannot be more than 12 months in the future.`);
                setLoadingSubmit(false);
                return;
            }
        }
        const volumesToSubmit = [];
        mountedShares.forEach(s => {
            // 1. If Local SSD is enabled
            if (s.use_local_ssd) {
                // Volume A: Local SSD Copy (Writable)
                // Uses the local path provided by backend, mounts to the user-specified path
                volumesToSubmit.push({
                    host_path: s.local_path,
                    container_path: s.container_path,
                    is_writable: true // Local copies are explicitly writable for the container
                });

                // Volume B: Synced NFS Copy (Read-Only)
                // Mounts to a 'synced_' prefix folder next to the main folder
                // e.g., if container_path is /home/user/mydata, synced is /home/user/synced_mydata
                const pathParts = s.container_path.split('/');
                const baseName = pathParts.pop() || ''; // Handle trailing slash edge case
                const dirName = pathParts.join('/');
                const syncedPath = `${dirName}${dirName === '/' ? '' : '/'}synced_${baseName}`;

                volumesToSubmit.push({
                    host_path: s.host_path, // The NFS path
                    container_path: syncedPath,
                    is_writable: false // Synced copy is read-only
                });
            } else {
                // 2. Standard NFS Mount
                volumesToSubmit.push({
                    host_path: s.host_path,
                    container_path: s.container_path,
                    is_writable: s.is_writable
                });
            }
        });
        const gpusString = formData.gpus.length > 0 ? formData.gpus.join(',') : 'none';
        const payload = {
            projectId: formData.projectId,
            serverId: formData.serverId,
            imageName: formData.imageId, // Send the selected ID (which is the role name 'worker_...') as 'imageName'
            gpus: gpusString,
            sshKeyId: formData.sshKeyId || null,
            password: formData.password,
            cpuLimit: formData.cpuLimit,
            ttlDate: formData.ttlDate,
            wants_public_ip: requestPublicIp,
            additional_volumes: volumesToSubmit,
        };
        if (!payload.projectId || !payload.serverId || !payload.imageName) {
            setError("Please select a project, server, and image.");
            setLoadingSubmit(false);
            return;
        }
        if (!payload.password && !payload.sshKeyId) {
            setError("A password or an SSH key is required.");
            setLoadingSubmit(false);
            return;
        }

        try {
            const response = await api.post('/api/containers', payload);
            onContainerCreated(response.data.container);
            // Reset form
            setFormData(prev => ({
                ...prev,
                imageId: '', // Reset image selection
                sshKeyId: '',
                gpus: ['0', '1', '2', '3'],
                cpuLimit: 'unlimited',
                password: '',
            }));
            setMountedShares([]);
        } catch (err) {
            console.error("Failed to create container:", err);
            setError(err.response?.data?.message || 'Failed to start container creation.');
        } finally {
            setLoadingSubmit(false);
        }
    };

    // Determine if main options are still loading
    const areOptionsLoading = loadingOptions.projects || loadingOptions.servers || loadingOptions.images || loadingOptions.keys || loadingOptions.shares;

    // --- Render ---
    if (areOptionsLoading && projects.length === 0 && servers.length === 0 && images.length === 0) { // Show loader only on initial load
        return <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}><CircularProgress /></Box>;
    }

    return (
        <>
            <Paper elevation={3} sx={{ p: 3, mb: 3 }}>
                <Typography variant="h5" gutterBottom sx={{ mb: 3 }}>Create New Container</Typography>
                {error && <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError('')}
                                 data-testid="container-form-error">{error}</Alert>}

                <Box component="form" onSubmit={handleSubmit} noValidate>
                    <Stack spacing={3}>

                        {/* 1. Project */}
                        <Paper elevation={1} sx={{ p: 2 }}>
                            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
                                <AccountTreeIcon color="action" />
                                <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>Project</Typography>
                            </Stack>
                            <Stack direction="row" spacing={2} alignItems="center">
                                <FormControl fullWidth required error={!formData.projectId && !!error && !loadingOptions.projects}>
                                    <InputLabel id="project-select-label">Project</InputLabel>
                                    <Select
                                        variant="filled"
                                        labelId="project-select-label"
                                        id="projectId" name="projectId"
                                        value={formData.projectId} label="Project"
                                        onChange={handleInputChange}
                                        disabled={loadingSubmit || loadingOptions.projects}
                                        SelectDisplayProps={{ 'data-testid': 'container-project-select' }}
                                    >
                                        <MenuItem value="" disabled><em>{loadingOptions.projects ? "Loading..." : "Select a project"}</em></MenuItem>
                                        {projects.map((p) => (
                                            <MenuItem key={p.id} value={p.id} data-testid={`container-project-option-${p.name}`}>{p.name}</MenuItem>
                                        ))}
                                    </Select>
                                    {projects.length === 0 && !loadingOptions.projects &&
                                        <FormHelperText>No projects found. Use '+' to create.</FormHelperText>}
                                </FormControl>
                                <IconButton
                                    aria-label="Create new project"
                                    onClick={() => setIsProjectModalOpen(true)}
                                    color="primary"
                                    disabled={loadingSubmit}
                                    data-testid="container-project-add"
                                    sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1 }}
                                >
                                    <AddIcon />
                                </IconButton>
                            </Stack>
                        </Paper>

                        {/* 2. Image */}
                        <Paper elevation={1} sx={{ p: 2 }}>
                            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
                                <LayersIcon color="action" />
                                <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>Image</Typography>
                            </Stack>
                            <FormControl fullWidth required error={!formData.imageId && !!error && !loadingOptions.images}>
                                <InputLabel id="image-select-label">Docker Image</InputLabel>
                                <Select
                                    variant="filled"
                                    labelId="image-select-label"
                                    id="imageId" name="imageId"
                                    value={formData.imageId} label="Docker Image"
                                    onChange={handleInputChange}
                                    disabled={loadingSubmit || loadingOptions.images}
                                    SelectDisplayProps={{ 'data-testid': 'container-image-select' }}
                                >
                                    <MenuItem value="" disabled><em>{loadingOptions.images ? "Loading..." : "Select an image"}</em></MenuItem>
                                    {images.map((i) => (
                                        <MenuItem key={i.id} value={i.id} data-testid={`container-image-option-${i.id}`}>{i.name}</MenuItem>
                                    ))}
                                </Select>
                                {images.length === 0 && !loadingOptions.images && <FormHelperText>No images available.</FormHelperText>}
                            </FormControl>
                        </Paper>

                        {/* 3. Container Password and SSH Key */}
                        <Paper elevation={1} sx={{ p: 2 }}>
                            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
                                <VpnKeyIcon color="action" />
                                <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>Credentials</Typography>
                            </Stack>
                            <Grid container spacing={2}>
                                <Grid item xs={12} md={6}>
                                    <TextField
                                        name="password"
                                        label="Container Password"
                                        type="password"
                                        value={formData.password}
                                        onChange={handleInputChange}
                                        disabled={loadingSubmit}
                                        required={!formData.sshKeyId}
                                        fullWidth
                                        error={!formData.password && !formData.sshKeyId && !!error}
                                        sx={{ minWidth: '20em' }}
                                        slotProps={{ htmlInput: { 'data-testid': 'container-password' } }}
                                    />
                                </Grid>
                                <Grid item xs={12} md={6}>
                                    <FormControl fullWidth error={!formData.sshKeyId && false} sx={{ minWidth: '20em' }}>
                                        <InputLabel id="sshkey-select-label">SSH Key (Optional)</InputLabel>
                                        <Select
                                            variant="filled"
                                            labelId="sshkey-select-label"
                                            id="sshKeyId" name="sshKeyId"
                                            value={formData.sshKeyId}
                                            label="SSH Key (Optional)"
                                            onChange={handleInputChange}
                                            disabled={loadingSubmit || loadingOptions.keys}
                                            SelectDisplayProps={{ 'data-testid': 'container-sshkey-select' }}
                                        >
                                            <MenuItem value="" data-testid="container-sshkey-option-none"><em>None Selected</em></MenuItem>
                                            {Array.isArray(sshKeys) && sshKeys.map((k) => (
                                                <MenuItem key={k.id} value={k.id} data-testid={`container-sshkey-option-${k.name}`}>{k.name}</MenuItem>
                                            ))}
                                        </Select>
                                        {loadingOptions.keys && <FormHelperText>Loading keys...</FormHelperText>}
                                        {!loadingOptions.keys && (!sshKeys || sshKeys.length === 0) &&
                                            <FormHelperText>No SSH keys found. Add one via the 'SSH Keys' tab.</FormHelperText>}
                                    </FormControl>
                                </Grid>
                            </Grid>
                        </Paper>

                        {/* 4. Additional Volumes */}
                        <Paper elevation={1} sx={{ p: 2 }}>
                            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                                <Stack direction="row" alignItems="center" spacing={1}>
                                    <StorageIcon color="action" />
                                    <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>Additional Volumes</Typography>
                                </Stack>
                                <Button
                                    variant="outlined"
                                    startIcon={<AddIcon />}
                                    onClick={() => setIsVolumeDialogOpen(true)}
                                    disabled={loadingSubmit || loadingOptions.shares}
                                    data-testid="container-volume-add"
                                >
                                    Add Volume
                                </Button>
                            </Box>

                            {mountedShares.length === 0 ? (
                                <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
                                    No additional volumes added. Click "Add Volume" to mount shared folders.
                                </Typography>
                            ) : (
                                <List dense>
                                    {mountedShares.map(share => (
                                        <ListItem
                                            key={share.host_path}
                                            data-testid={`mounted-volume-${share.host_path}`}
                                            sx={{
                                                border: share.use_local_ssd ? '1px solid #1976d2' : '1px solid rgba(0, 0, 0, 0.12)',
                                                borderRadius: 1,
                                                mb: 1,
                                                p: 1
                                            }}
                                            secondaryAction={
                                                <IconButton edge="end" onClick={() => handleRemoveShare(share.host_path)}
                                                            aria-label="Remove volume"
                                                            data-testid={`mounted-volume-remove-${share.host_path}`}>
                                                    <DeleteIcon />
                                                </IconButton>
                                            }
                                        >
                                            <Box sx={{ width: '100%', pr: 4 }}>
                                                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                                                    <Box>
                                                        <Typography variant="subtitle2">{share.name}</Typography>
                                                        <Typography variant="caption" color="text.secondary">
                                                            {share.is_writable ? 'Read/Write' : 'Read-Only'}
                                                        </Typography>
                                                    </Box>
                                                    {/* Local SSD Toggle */}
                                                    <Box sx={{ display: 'flex', alignItems: 'center' }}>
                                                        {share.use_local_ssd && (
                                                            <Tooltip title="Warning: Local copies must be manually created by Pina. If enabled, a read-only 'synced_' folder will also be mounted.">
                                                                <InfoIcon color="warning" fontSize="small" sx={{ mr: 1 }} />
                                                            </Tooltip>
                                                        )}
                                                        <FormControlLabel
                                                            control={
                                                                <Switch
                                                                    checked={share.use_local_ssd}
                                                                    onChange={() => handleToggleLocal(share.host_path)}
                                                                    size="small"
                                                                />
                                                            }
                                                            label={<Typography variant="caption">Local SSD</Typography>}
                                                        />
                                                    </Box>
                                                </Box>
                                                <TextField
                                                    size="small"
                                                    label="Container Mount Path"
                                                    value={share.container_path}
                                                    onChange={(e) => handleSharePathChange(share.host_path, e.target.value)}
                                                    fullWidth
                                                    variant="outlined"
                                                    slotProps={{ htmlInput: { 'data-testid': `mounted-volume-path-${share.host_path}` } }}
                                                />
                                            </Box>
                                        </ListItem>
                                    ))}
                                </List>
                            )}
                        </Paper>

                        {/* 5. Compute Server */}
                        <Paper elevation={1} sx={{ p: 2 }}>
                            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
                                <DnsIcon color="action" />
                                <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>Compute Server</Typography>
                            </Stack>
                            <FormControl fullWidth required error={!formData.serverId && !!error && !loadingOptions.servers}>
                                <InputLabel id="server-select-label">Compute Server</InputLabel>
                                <Select
                                    variant="filled"
                                    labelId="server-select-label"
                                    id="serverId" name="serverId"
                                    value={formData.serverId} label="Compute Server"
                                    onChange={handleInputChange}
                                    disabled={loadingSubmit || loadingOptions.servers}
                                    SelectDisplayProps={{ 'data-testid': 'container-server-select' }}
                                >
                                    <MenuItem value="" disabled><em>{loadingOptions.servers ? "Loading..." : "Select a server"}</em></MenuItem>
                                    {servers.map((s) => (
                                        <MenuItem key={s.id} value={s.id} data-testid={`container-server-option-${s.hostname}`}>{s.hostname}</MenuItem>
                                    ))}
                                </Select>
                                {servers.length === 0 && !loadingOptions.servers && <FormHelperText>No servers available.</FormHelperText>}
                            </FormControl>

                            {/* Public IP Checkbox inside Server card */}
                            {publicIpConfig.isVisible && (
                                <Box sx={{ mt: 2 }}>
                                    <FormControlLabel
                                        control={
                                            <Checkbox
                                                checked={requestPublicIp}
                                                onChange={(e) => setRequestPublicIp(e.target.checked)}
                                                disabled={publicIpConfig.isDisabled || loadingSubmit}
                                                slotProps={{ input: { 'data-testid': 'container-public-ip' } }}
                                            />
                                        }
                                        label="Request Public IP"
                                    />
                                    {publicIpConfig.helperText && <FormHelperText>{publicIpConfig.helperText}</FormHelperText>}
                                </Box>
                            )}
                        </Paper>

                        {/* 6. CPU Limit */}
                        {selectedServer && (
                            <Paper elevation={1} sx={{ p: 2 }}>
                                <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
                                    <SpeedIcon color="action" />
                                    <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>CPU Limit</Typography>
                                </Stack>
                                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
                                    Limit the number of CPU cores this container can use.
                                    {selectedServer && selectedServer.cpu_limit !== undefined && selectedServer.cpu_limit !== null
                                        ? ` Max allowed: ${selectedServer.cpu_limit}`
                                        : ' Max allowed: Unlimited'}
                                </Typography>
                                <TextField
                                    name="cpuLimit"
                                    label="CPU Limit"
                                    value={formData.cpuLimit}
                                    onChange={handleInputChange}
                                    disabled={loadingSubmit}
                                    fullWidth
                                    helperText='Use "unlimited" or a number (e.g. 0.5)'
                                    slotProps={{ htmlInput: { 'data-testid': 'container-cpu-limit' } }}
                                />
                                <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
                                    {["unlimited", "0.5", "1", "4"].map(limit => (
                                        <Button key={limit} variant="outlined" size="small" onClick={() => handleCpuLimitQuickSelect(limit)}>{limit === "unlimited" ? "Unlimited" : limit}</Button>
                                    ))}
                                </Stack>
                            </Paper>
                        )}

                        {/* 7. GPU Selection */}
                        {selectedServer && (
                            <Paper elevation={1} sx={{ p: 2 }}>
                                <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
                                    <DeveloperBoardIcon color="action" />
                                    <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>GPU Selection</Typography>
                                </Stack>
                                {selectedServer && selectedServer.gpu_count > 0 ? (
                                    <FormControl component="fieldset" variant="standard">
                                        <FormGroup row>
                                            {gpuOptions.map((gpuNum) => {
                                                const allowed = allowedGpus.includes(gpuNum);
                                                return (
                                                    <Tooltip key={gpuNum} title={allowed ? '' : "Your groups don't include this GPU"}>
                                                        <FormControlLabel
                                                            disabled={!allowed || loadingSubmit}
                                                            control={
                                                                <Checkbox
                                                                    checked={formData.gpus.includes(gpuNum)}
                                                                    onChange={handleGpuChange}
                                                                    value={gpuNum}
                                                                    disabled={!allowed || loadingSubmit}
                                                                    slotProps={{ input: { 'data-testid': `container-gpu-${gpuNum}` } }}
                                                                />
                                                            }
                                                            label={`GPU ${gpuNum}`}
                                                        />
                                                    </Tooltip>
                                                );
                                            })}
                                        </FormGroup>
                                        {gpuOptions.some(gpu => !allowedGpus.includes(gpu)) && (
                                            <FormHelperText data-testid="container-gpu-restricted">
                                                Greyed-out GPUs are not available to you. An admin can change your groups.
                                            </FormHelperText>
                                        )}
                                    </FormControl>
                                ) : (
                                    <Typography variant="body2" color="text.secondary">
                                        {selectedServer ? "This is a CPU-only server (0 GPUs)." : "Select a server first."}
                                    </Typography>
                                )}
                            </Paper>
                        )}

                        {/* 8. TTL */}
                        {ttlConfig.isVisible && (
                            <Paper elevation={1} sx={{ p: 2 }}>
                                <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
                                    <AccessTimeIcon color="action" />
                                    <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>Auto-Deletion (TTL)</Typography>
                                </Stack>
                                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
                                    This container uses a local image. To keep the servers SSD from filling up, please specify when this container should be automatically removed.
                                    {ttlConfig.isRequired && <strong> Maximum duration is 12 months.</strong>}
                                </Typography>
                                <TextField
                                    name="ttlDate"
                                    label="Deletion Date"
                                    type="date"
                                    value={formData.ttlDate}
                                    onChange={handleInputChange}
                                    fullWidth
                                    slotProps={{
                                        inputLabel: { shrink: true },
                                        htmlInput: {
                                            min: ttlConfig.minDate,
                                            max: ttlConfig.maxDate,
                                            'data-testid': 'container-ttl-date'
                                        }
                                    }}
                                    required={ttlConfig.isRequired}
                                    disabled={loadingSubmit}
                                />
                                <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
                                    <Chip label="3 Months" onClick={() => handleTtlQuickSelect(3)} clickable size="small" color="primary" variant="outlined"
                                          data-testid="container-ttl-3m" />
                                    <Chip label="6 Months" onClick={() => handleTtlQuickSelect(6)} clickable size="small" color="primary" variant="outlined"
                                          data-testid="container-ttl-6m" />
                                    <Chip label="1 Year" onClick={() => handleTtlQuickSelect(12)} clickable size="small" color="primary" variant="outlined"
                                          data-testid="container-ttl-12m" />
                                </Stack>
                            </Paper>
                        )}

                        {/* 9. Start Button */}
                        <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 2 }}>
                            <Button
                                type="submit"
                                variant="contained"
                                size="large"
                                disabled={loadingSubmit}
                                sx={{ minWidth: '150px' }}
                                data-testid="container-submit"
                            >
                                {loadingSubmit ? "Starting..." : "Start Container"}
                            </Button>
                        </Box>
                    </Stack>
                </Box>
            </Paper>

            <ProjectModal
                open={isProjectModalOpen}
                onClose={() => setIsProjectModalOpen(false)}
                onProjectSaved={handleProjectCreatedInForm}
            />

            {/* Volume Selection Dialog */}
            <Dialog open={isVolumeDialogOpen} onClose={() => setIsVolumeDialogOpen(false)} fullWidth maxWidth="sm">
                <DialogTitle>Mount Additional Volume</DialogTitle>
                <DialogContent>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                        Select a shared folder or project volume to mount into your container.
                    </Typography>
                    <FormControl fullWidth margin="dense">
                        <InputLabel>Available Shared Folders & Projects</InputLabel>
                        <Select
                            value={shareToMount}
                            label="Available Shared Folders & Projects"
                            onChange={(e) => setShareToMount(e.target.value)}
                            SelectDisplayProps={{ 'data-testid': 'volume-select' }}
                        >
                            <MenuItem value="" disabled><em>Select a folder to mount</em></MenuItem>
                            {filteredAvailableShares.filter(s => !mountedShares.some(ms => ms.host_path === s.host_path)).map(s => (
                                <MenuItem key={s.host_path} value={s.host_path} data-testid={`volume-option-${s.host_path}`}>
                                    {s.name} ({s.is_writable ? 'rw' : 'ro'})
                                </MenuItem>
                            ))}
                        </Select>
                    </FormControl>
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setIsVolumeDialogOpen(false)}>Cancel</Button>
                    <Button
                        onClick={() => {
                            handleAddShare();
                            setIsVolumeDialogOpen(false);
                        }}
                        disabled={!shareToMount}
                        variant="contained"
                        data-testid="volume-add-confirm"
                    >
                        Add Volume
                    </Button>
                </DialogActions>
            </Dialog>
        </>
    );
}

export default ContainerForm;