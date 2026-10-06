import React, {useState, useEffect, useRef, useCallback, useMemo} from 'react';
import io from 'socket.io-client';
import {
    Box,
    Typography,
    Grid,
    Paper,
    Button,
    CircularProgress,
    Alert,
    Link,
    IconButton,
    Tooltip,
    Collapse,
    Chip,
    Stack
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PauseIcon from '@mui/icons-material/Pause';
import StopIcon from '@mui/icons-material/Stop';
import DeleteIcon from '@mui/icons-material/Delete';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import AutorenewIcon from '@mui/icons-material/Autorenew';
import api from '../services/api';

// Helper to format date
const formatDate = (isoString) => {
    if (!isoString) return 'N/A';
    try {
        return new Date(isoString).toLocaleString();
    } catch (e) {
        return 'Invalid Date';
    }
};

// Status color mapping
const statusColors = {
    RUNNING: 'success',
    STARTING: 'info',
    PENDING: 'warning',
    PAUSING: 'warning',
    PAUSED: 'default',
    STOPPING: 'warning',
    STOPPED: 'default',
    DELETING: 'warning',
    DELETED: 'error',
    ERROR: 'error',
};

// Determine Socket.IO URL
const SOCKET_URL = (process.env.NODE_ENV === 'production')
    ? window.location.origin // Assumes Socket.IO served from same origin
    : (process.env.REACT_APP_SOCKET_URL || 'http://localhost:5000');

function ContainerDetails({container, onUpdate, onDelete}) {
    const [loadingAction, setLoadingAction] = useState(null); // 'pause', 'stop', 'delete', 'resume'
    const [actionError, setActionError] = useState('');
    const [expanded, setExpanded] = useState(false); // State for logs expansion
    const [liveLogs, setLiveLogs] = useState([]);
    const socketRef = useRef(null); // To hold the socket instance
    const logDisplayRef = useRef(null); // For auto-scrolling
    const onUpdateRef = useRef(onUpdate);
    const onDeleteRef = useRef(onDelete);
    const isJobRunning = ['PENDING', 'STARTING', 'PAUSING', 'STOPPING', 'DELETING'].includes(container.status);

    useEffect(() => {
        onUpdateRef.current = onUpdate;
        onDeleteRef.current = onDelete;
    }, [onUpdate, onDelete]);

    const fetchLatestContainerData = useCallback(() => {
        api.get(`/api/containers/${container.id}`)
            .then(response => {
                onUpdateRef.current(response.data); // Update parent state with fresh data
            })
            .catch(err => {
                console.error(`[Fetch] Failed to get final state for container ${container.id}:`, err);
                setActionError('Could not refresh container state. Please refresh the page.');
            });
    }, [container.id]); // stable except when the container id itself changes

    const constructedSshCommand = useMemo(() => {
        if (container.status === 'RUNNING' && container.ip_address && container.username) {
            let cmd = `ssh ${container.username}@${container.ip_address}`;
            if (container.server_ssh_port && container.server_ssh_port !== 22) {
                cmd += ` -p ${container.server_ssh_port}`;
            }
            return cmd;
        }
        return null;
    }, [container.status, container.ip_address, container.username, container.server_ssh_port]);

    useEffect(() => {
        // Connect socket if a job is running and we don't already have a connection.
        if (isJobRunning && container.id && !socketRef.current) {
            setExpanded(true); // Auto-expand logs when a job starts
            setLiveLogs([]);   // Clear previous live logs

            console.log(`[SocketIO C:${container.id}] Job running (status: ${container.status}). Connecting to ${SOCKET_URL}`);
            const newSocket = io(SOCKET_URL, {
                transports: ['websocket'],
                query: {container_id: container.id} // Pass container ID in query for room joining
            });
            socketRef.current = newSocket;

            newSocket.on('connect', () => {
                console.log(`[SocketIO C:${container.id}] Connected. Emitting join_log_room.`);
                newSocket.emit('join_log_room', {container_id: String(container.id)});
            });

            newSocket.on('ansible_log', (logEntry) => {
                if (String(logEntry.container_id) === String(container.id)) {
                    setLiveLogs(prevLogs => [...prevLogs, logEntry.line]);
                }
            });

            newSocket.on('ansible_job_completed', (data) => {
                if (String(data.container_id) === String(container.id)) {
                    // Check if the backend confirmed the container was deleted.
                    if (data.status === 'DELETED') {
                        console.log(`[SocketIO C:${container.id}] Deletion confirmed by backend. Removing from UI.`);
                        // Call the onDelete prop passed from DashboardPage to remove it from the list.
                        onDeleteRef.current(container.id);
                    } else {
                        // For all other cases (RUNNING, STOPPED, ERROR, etc.), fetch the final state.
                        console.log(`[SocketIO C:${container.id}] Job completed with status '${data.status}'. Fetching final state.`);
                        fetchLatestContainerData();
                    }
                }
            });

            newSocket.on('connect_error', (err) => {
                console.error(`[SocketIO C:${container.id}] Connection Error:`, err.message);
                setLiveLogs(prev => [...prev, `[WebSocket Connection Error: ${err.message}]`]);
            });
        }

        // Cleanup function: runs when isJobRunning becomes false or component unmounts.
        return () => {
            if (socketRef.current) {
                console.log(`[SocketIO C:${container.id}] Cleanup: Disconnecting socket.`);
                socketRef.current.disconnect();
                socketRef.current = null;
            }
        };
    }, [container.id, isJobRunning, fetchLatestContainerData]);

    // Auto-scroll logs to the bottom
    useEffect(() => {
        if (logDisplayRef.current) {
            logDisplayRef.current.scrollTop = logDisplayRef.current.scrollHeight;
        }
    }, [liveLogs]);

    const handleAction = async (action) => {
        setLoadingAction(action);
        setActionError('');
        let requestPromise;
        const url = `/api/containers/${container.id}`;
        const originalStatus = container.status;

        try {
            switch (action) {
                case 'pause':
                    requestPromise = api.post(`${url}/pause`);
                    break;
                case 'resume':
                    requestPromise = api.post(`${url}/resume`);
                    break;
                case 'stop':
                    requestPromise = api.post(`${url}/stop`);
                    break;
                case 'delete':
                    requestPromise = api.delete(url);
                    break;
                case 'prolong':
                    requestPromise = api.post(`${url}/prolong`);
                    break;
                default:
                    console.error('Invalid action: ' + action);
            }

            const response = await requestPromise;

            // The API now returns the container with an optimistic status (e.g., 'PAUSING')
            // and a job ID. We update the state, which triggers the `isJobRunning` useEffect.
            if (response.data && response.data.container) {
                onUpdate(response.data.container);
            } else if (action === 'delete' && response.status === 202) {
                onUpdate({...container, status: 'DELETING'});
            }

        } catch (err) {
            console.error(`Failed to ${action} container:`, err);
            const errorMsg = err.response?.data?.message || `Failed to perform action: ${action}.`;
            setActionError(errorMsg);
            // Rollback optimistic update on error
            onUpdate({...container, status: originalStatus});
        } finally {
            setLoadingAction(null); // Stop loading indicator
        }
    };

    const handleCopySSH = () => {
        if (constructedSshCommand) {
            navigator.clipboard.writeText(constructedSshCommand)
                .then(() => {
                })
                .catch(err => console.error('Failed to copy SSH command:', err));
        }
    };

    const canPause = container.status === 'RUNNING';
    const canResume = ['PAUSED', 'STOPPED'].includes(container.status);
    const canStop = ['RUNNING', 'PAUSED'].includes(container.status);
    const canDelete = !['DELETING', 'DELETED'].includes(container.status);
    const canProlong = container.ttl_date && !['DELETING', 'DELETED', 'PENDING', 'STARTING'].includes(container.status);
    const isAnyActionInProgress = loadingAction || isJobRunning;

    const getTtlColor = () => {
        if (!container.ttl_date) return 'text.secondary';
        const daysLeft = (new Date(container.ttl_date) - new Date()) / (1000 * 60 * 60 * 24);
        if (daysLeft < 7) return 'error.main';
        if (daysLeft < 30) return 'warning.main';
        return 'text.secondary';
    };

    const renderLogContent = () => {
        if (liveLogs.length > 0) {
            return liveLogs.join('\n');
        }
        if (isJobRunning) {
            // Show the log from the last DB state while waiting for live logs
            return container.ansible_log || "Process active, waiting for initial logs...";
        }
        // If no job is running, show the final log from the DB
        return container.ansible_log || "No logs available.";
    };

    // The data-* attributes expose state to end-to-end tests, which locate a
    // card by project and image and wait on data-status rather than on text.
    return (
        <Paper elevation={2} sx={{p: 2, mb: 2}}
               data-testid="container-card"
               data-container-id={container.id}
               data-project={container.project}
               data-image={container.image}
               data-status={container.status}>
            <Grid container spacing={2} alignItems="center">
                <Grid item xs={12} sm={6} md={3}>
                    <Typography variant="h6" component="div">
                        {container.project}
                    </Typography>
                    <Typography variant="body2" color="textSecondary">
                        Image: {container.image}
                    </Typography>
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                    <Chip
                        label={container.status}
                        color={statusColors[container.status] || 'default'}
                        size="small"
                        sx={{mr: 1}}
                        data-testid="container-status"
                    />
                    {isJobRunning && <CircularProgress size={16} sx={{verticalAlign: 'middle'}}/>}
                    <Typography variant="body2" color="textSecondary" sx={{mt: 0.5}}>
                        On: {container.server} (GPUs: {container.gpus || 'N/A'})
                    </Typography>
                    {container.ttl_date && (
                        <Typography variant="caption" display="block" sx={{mt: 0.5, color: getTtlColor()}}>
                            TTL Expires: {formatDate(container.ttl_date)}
                        </Typography>
                    )}
                </Grid>
                <Grid item xs={12} md={4}>
                    {container.status === 'RUNNING' && container.ip_address ? (
                        <Box>
                            <Typography variant="body2" component="span">
                                IP: <span data-testid="container-ip">{container.ip_address}</span> | SSH:&nbsp;
                            </Typography>
                            <Tooltip title={constructedSshCommand || 'SSH command not available'}>
                                <span>
                                    <Link component="button" variant="body2" onClick={handleCopySSH}
                                          disabled={!constructedSshCommand}>
                                        <code data-testid="container-ssh-command">{constructedSshCommand}</code>
                                        {constructedSshCommand &&
                                            <ContentCopyIcon sx={{fontSize: 14, ml: 0.5, verticalAlign: 'middle'}}/>}
                                    </Link>
                                </span>
                            </Tooltip>
                        </Box>
                    ) : (
                        <Typography variant="body2" color="textSecondary">IP not available</Typography>
                    )}
                    <Typography variant="caption" color="textSecondary" display="block">
                        Created: {formatDate(container.created_at)}
                        {container.ssh_key_name && ` | Key: ${container.ssh_key_name}`}
                    </Typography>
                </Grid>
                <Grid item xs={12} md={2}>
                    <Stack direction="row" spacing={1} justifyContent="flex-end">
                        <Tooltip title="Prolong by 4 Weeks">
                            <span>
                                <IconButton
                                    size="small"
                                    onClick={() => handleAction('prolong')}
                                    data-testid="container-action-prolong"
                                    disabled={!canProlong || isAnyActionInProgress}
                                    color="primary"
                                >
                                    {loadingAction === 'prolong' ? <CircularProgress size={20}/> : <AutorenewIcon/>}
                                </IconButton>
                            </span>
                        </Tooltip>
                        <Tooltip title="Resume/Start">
                            <span>
                                <IconButton
                                    size="small"
                                    onClick={() => handleAction('resume')}
                                    data-testid="container-action-resume"
                                    disabled={!canResume || isAnyActionInProgress}
                                    color="success"
                                >
                                    {loadingAction === 'resume' ? <CircularProgress size={20}/> : <PlayArrowIcon/>}
                                </IconButton>
                            </span>
                        </Tooltip>
                        <Tooltip title="Pause">
                            <span>
                                <IconButton
                                    size="small"
                                    onClick={() => handleAction('pause')}
                                    data-testid="container-action-pause"
                                    disabled={!canPause || isAnyActionInProgress}
                                    color="warning"
                                >
                                    {loadingAction === 'pause' ? <CircularProgress size={20}/> : <PauseIcon/>}
                                </IconButton>
                            </span>
                        </Tooltip>
                        <Tooltip title="Stop">
                            <span>
                            <IconButton
                                size="small"
                                onClick={() => handleAction('stop')}
                                data-testid="container-action-stop"
                                disabled={!canStop || isAnyActionInProgress}
                                color="error"
                            >
                                {loadingAction === 'stop' ? <CircularProgress size={20}/> : <StopIcon/>}
                            </IconButton>
                            </span>
                        </Tooltip>
                        <Tooltip title="Delete">
                            <span>
                                <IconButton
                                    size="small"
                                    onClick={() => handleAction('delete')}
                                    data-testid="container-action-delete"
                                    disabled={!canDelete || isAnyActionInProgress}
                                    color="secondary"
                                >
                                    {loadingAction === 'delete' ? <CircularProgress size={20}/> : <DeleteIcon/>}
                                </IconButton>
                            </span>
                        </Tooltip>
                    </Stack>
                </Grid>

                {actionError && (
                    <Grid item xs={12}>
                        <Alert severity="error" onClose={() => setActionError('')}
                               data-testid="container-action-error">{actionError}</Alert>
                    </Grid>
                )}

                {(isJobRunning || container.ansible_log) && (
                    <Grid item xs={12}>
                        <Button
                            size="small"
                            onClick={() => setExpanded(!expanded)}
                            startIcon={expanded ? <ExpandLessIcon/> : <ExpandMoreIcon/>}
                            aria-expanded={expanded}
                            data-testid="container-logs-toggle"
                        >
                            Show Logs
                        </Button>
                        <Collapse in={expanded} timeout="auto" unmountOnExit>
                            <Paper
                                ref={logDisplayRef}
                                elevation={0}
                                sx={{
                                    mt: 1, p: 2,
                                    maxHeight: 400,
                                    overflowY: 'auto',
                                    backgroundColor: 'grey.900',
                                    color: 'grey.200',
                                    border: '1px solid #444'
                                }}
                            >
                                <Typography component="pre" sx={{
                                    whiteSpace: 'pre-wrap',
                                    wordBreak: 'break-all',
                                    fontFamily: 'monospace',
                                    fontSize: '0.8rem'
                                }}
                                    data-testid="container-log"
                                    data-log-source={liveLogs.length > 0 ? 'live' : 'stored'}
                                    data-live-lines={liveLogs.length}
                                >
                                    {renderLogContent()}
                                    {isJobRunning && <span className="blinking-cursor">|</span>}
                                </Typography>
                            </Paper>
                        </Collapse>
                    </Grid>
                )}
            </Grid>
        </Paper>
    );
}

export default ContainerDetails;