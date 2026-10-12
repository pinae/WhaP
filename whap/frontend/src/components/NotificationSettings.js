import React, { useCallback, useEffect, useState } from 'react';
import {
    Alert, AlertTitle, Box, Button, Checkbox, Chip, CircularProgress, Dialog, DialogActions, DialogContent,
    DialogTitle, Divider, FormControlLabel, Paper, Stack, Switch, TextField, Typography,
} from '@mui/material';
import EmailIcon from '@mui/icons-material/Email';
import ChatIcon from '@mui/icons-material/Chat';
import ComputerIcon from '@mui/icons-material/Computer';
import LayersIcon from '@mui/icons-material/Layers';
import StorageIcon from '@mui/icons-material/Storage';
import HourglassBottomIcon from '@mui/icons-material/HourglassBottom';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import api from '../services/api';

const URL = '/api/notification-settings';

// "7 days and 1 day before"
export function daysBefore(days) {
    const parts = days.map(d => `${d} ${d === 1 ? 'day' : 'days'}`);
    const joined = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}` : parts[0];
    return `${joined} before`;
}

const TOPICS = [
    { key: 'maintenance', icon: <ComputerIcon />, title: 'Server maintenance', protects: true,
      text: () => 'A compute server running one of your containers will be restarted or taken offline.' },
    { key: 'expiry', icon: <HourglassBottomIcon />, title: 'Expiring local containers', protects: true,
      text: (days) => `${daysBefore(days)} a local project directory is deleted, with a link to prolong it.` },
    { key: 'image', icon: <LayersIcon />, title: 'Image updates',
      text: () => 'A newer version of an image you use is available.' },
    { key: 'dataset', icon: <StorageIcon />, title: 'Dataset updates',
      text: () => 'A dataset mounted in one of your containers has new data.' },
];

function Row({ icon, title, children, action }) {
    return (
        <Stack direction="row" spacing={2} alignItems="flex-start" sx={{ py: 1.5 }}>
            <Box sx={{ pt: 0.5, color: 'action.active', display: 'flex' }}>{icon}</Box>
            <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                <Typography variant="subtitle1">{title}</Typography>
                {children}
            </Box>
            {action && <Box>{action}</Box>}
        </Stack>
    );
}

/** Asked before a change that leaves WhaP unable to warn the user. */
export function RiskDialog({ open, allOff, onKeep, onConfirm, busy }) {
    const [understood, setUnderstood] = useState(false);
    useEffect(() => { if (open) setUnderstood(false); }, [open]);
    return (
        <Dialog open={open} onClose={onKeep} maxWidth="sm" fullWidth data-testid="risk-dialog">
            <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <WarningAmberIcon color="warning" />
                {allOff ? 'Turn off all notifications?' : 'Turn off the warnings that protect your data?'}
            </DialogTitle>
            <DialogContent>
                <Typography variant="body2" sx={{ mb: 1.5 }}>WhaP will have no way to tell you when:</Typography>
                <Box component="ul" sx={{ mt: 0, pl: 3, '& li': { mb: 1 } }}>
                    <li><Typography variant="body2"><b>a server is restarted</b>: your containers are stopped
                        and running jobs end, without warning.</Typography></li>
                    <li><Typography variant="body2"><b>a local project expires</b>: its directory on the compute
                        server, with everything not in <code>~/synced</code>, is deleted on the ttl date.</Typography></li>
                </Box>
                <FormControlLabel sx={{ mt: 1 }}
                                  control={<Checkbox checked={understood} onChange={e => setUnderstood(e.target.checked)}
                                                     slotProps={{ input: { 'data-testid': 'risk-acknowledge' } }} />}
                                  label={<Typography variant="body2">I understand that my containers may be stopped
                                      or deleted without prior warning.</Typography>} />
            </DialogContent>
            <DialogActions>
                <Button variant="contained" onClick={onKeep} data-testid="risk-keep">Keep notifications on</Button>
                <Button color="error" onClick={onConfirm} disabled={!understood || busy} data-testid="risk-confirm">
                    {allOff ? 'Turn all off' : 'Turn off'}
                </Button>
            </DialogActions>
        </Dialog>
    );
}

function MatrixRow({ view, run, busy }) {
    const matrix = view.matrix;
    const [matrixId, setMatrixId] = useState(matrix.id || matrix.suggestion || '');
    const [code, setCode] = useState('');
    const [changing, setChanging] = useState(false);
    useEffect(() => {
        if (!matrix.pending_id) setCode('');
        if (matrix.pending_id) setChanging(false);
    }, [matrix.pending_id]);

    if (!matrix.available) {
        return (
            <Row icon={<ChatIcon />} title="Matrix">
                <Typography variant="body2" color="text.secondary">This WhaP has no Matrix bot.</Typography>
            </Row>
        );
    }
    if (matrix.pending_id) {
        return (
            <Row icon={<ChatIcon />} title="Matrix">
                <Typography variant="body2" sx={{ mb: 1.5 }}>
                    WhaP's bot has invited <b>{matrix.pending_id}</b> to a chat and sent a six-digit code.
                    Accept the invitation in your Matrix app and enter the code here.
                    {matrix.id && <> Until then, notifications still go to {matrix.id}.</>}
                </Typography>
                <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                    <TextField size="small" label="Code" value={code} onChange={e => setCode(e.target.value)}
                               sx={{ width: 160 }} autoFocus slotProps={{ htmlInput: { inputMode: 'numeric',
                               'data-testid': 'settings-matrix-code' } }} />
                    <Button variant="contained" disabled={busy || code.trim().length !== 6}
                            onClick={() => run('post', `${URL}/matrix/verify`, { code: code.trim() })}
                            data-testid="settings-matrix-verify">Connect</Button>
                    <Button disabled={busy} onClick={() => run('post', `${URL}/matrix`, { matrix_id: matrix.pending_id })}>
                        Send a new code</Button>
                    <Button disabled={busy} onClick={() => run('delete', `${URL}/matrix/pending`)}>Cancel</Button>
                </Stack>
            </Row>
        );
    }
    if (matrix.id && !changing) {
        return (
            <Row icon={<ChatIcon />} title="Matrix"
                 action={<Switch checked={matrix.enabled} disabled={busy}
                                 onChange={e => run('put', URL, { matrix_enabled: e.target.checked })}
                                 slotProps={{ input: { 'aria-label': 'Matrix', 'data-testid': 'settings-matrix-switch' } }} />}>
                <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                    <Typography variant="body2" data-testid="settings-matrix-id">{matrix.id}</Typography>
                    <Chip size="small" color="success" variant="outlined" icon={<CheckCircleIcon />} label="Connected" />
                    <Button size="small" disabled={busy} onClick={() => { setMatrixId(matrix.id); setChanging(true); }}
                            data-testid="settings-matrix-change">Change</Button>
                    <Button size="small" disabled={busy} onClick={() => run('delete', `${URL}/matrix`)}
                            data-testid="settings-matrix-disconnect">Disconnect</Button>
                </Stack>
            </Row>
        );
    }
    const isSuggestion = matrix.suggestion && matrixId.trim() === matrix.suggestion;
    return (
        <Row icon={<ChatIcon />} title="Matrix">
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                {matrix.id ? `Connected: ${matrix.id}. Enter the Matrix ID to use instead.`
                    : "Optional. Get the same notifications as a chat message from WhaP's bot."}
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="flex-start">
                <TextField size="small" label="Matrix ID" placeholder="@you:example.org" value={matrixId}
                           onChange={e => setMatrixId(e.target.value)} sx={{ width: 320, maxWidth: '100%' }}
                           helperText={isSuggestion ? 'Your university account. Change it if yours is different.' : ' '}
                           slotProps={{ htmlInput: { 'data-testid': 'settings-matrix-input' } }} />
                <Button variant="outlined" disabled={busy || !matrixId.trim() || matrixId.trim() === matrix.id}
                        onClick={() => run('post', `${URL}/matrix`, { matrix_id: matrixId.trim() })}
                        data-testid="settings-matrix-connect" sx={{ mt: '2px' }}>Connect</Button>
                {matrix.id && <Button onClick={() => setChanging(false)} sx={{ mt: '2px' }}>Cancel</Button>}
            </Stack>
        </Row>
    );
}

function emailNote(email) {
    if (!email.available) return 'This WhaP sends no email.';
    if (!email.address) return 'Your account has no email address. Ask an admin to add one.';
    return null;
}

/** Where and about what WhaP notifies the logged-in user. Every change is saved at once. */
function NotificationSettings() {
    const [view, setView] = useState(null);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [risk, setRisk] = useState(null);  // {request, allOff} while the dialog is open
    const [testResults, setTestResults] = useState(null);

    useEffect(() => {
        api.get(URL).then(r => setView(r.data)).catch(() => setError('Could not load your settings.'));
    }, []);

    const run = useCallback(async (method, url, body) => {
        setBusy(true);
        setError('');
        try {
            const response = method === 'delete'
                ? await api.delete(url, body ? { data: body } : undefined)
                : await api[method](url, body);
            setView(response.data);
            setRisk(null);
        } catch (err) {
            const data = err.response?.data || {};
            if (err.response?.status === 409 && data.needs_acknowledgement) {
                setRisk({ request: { method, url, body }, allOff: data.all_off });
            } else {
                setError(data.message || 'Saving failed.');
            }
        } finally {
            setBusy(false);
        }
    }, []);

    const confirmRisk = () => {
        const { method, url, body } = risk.request;
        run(method, url, { ...(body || {}), acknowledge_risk: true });
    };

    const sendTest = async () => {
        setBusy(true);
        setTestResults(null);
        try {
            setTestResults((await api.post(`${URL}/test`)).data.results);
        } catch (err) {
            setError(err.response?.data?.message || 'The test could not be sent.');
        } finally {
            setBusy(false);
        }
    };

    if (!view) {
        return error ? <Alert severity="error">{error}</Alert>
            : <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}><CircularProgress /></Box>;
    }

    const reachable = view.reachable.length > 0;
    const canTurnBackOn = view.email.available && view.email.address;

    return (
        <Stack spacing={3}>
            {!view.protects_data && (
                <Alert severity="warning" data-testid="notifications-off-banner"
                       action={canTurnBackOn && (
                           <Button color="inherit" size="small" sx={{ whiteSpace: 'nowrap' }} disabled={busy}
                                   onClick={() => run('put', URL, { email_enabled: true,
                                       topics: { maintenance: true, expiry: true } })}>
                               Turn back on</Button>)}>
                    <AlertTitle>WhaP can't warn you</AlertTitle>
                    Your containers may be stopped for maintenance, and local project directories deleted when they
                    expire, without any warning.
                </Alert>
            )}
            {error && <Alert severity="error" onClose={() => setError('')} data-testid="settings-error">{error}</Alert>}

            <Paper sx={{ p: 3 }}>
                <Typography variant="h6">Where to reach you</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    Every notification goes to each place that is switched on.
                </Typography>
                <Row icon={<EmailIcon />} title="Email"
                     action={<Switch checked={view.email.enabled} disabled={busy}
                                     onChange={e => run('put', URL, { email_enabled: e.target.checked })}
                                     slotProps={{ input: { 'aria-label': 'Email', 'data-testid': 'settings-email-switch' } }} />}>
                    {view.email.address && <Typography variant="body2">{view.email.address}</Typography>}
                    {emailNote(view.email)
                        ? <Typography variant="caption" color="warning.main">{emailNote(view.email)}</Typography>
                        : <Typography variant="caption" color="text.secondary">From your account.</Typography>}
                </Row>
                <Divider />
                <MatrixRow view={view} run={run} busy={busy} />
                <Divider sx={{ mb: 2 }} />
                <Button variant="outlined" size="small" disabled={busy || !reachable} onClick={sendTest}
                        data-testid="settings-test">Send me a test notification</Button>
                {testResults && (
                    <Stack spacing={1} sx={{ mt: 2 }}>
                        {testResults.map(r => (
                            <Alert key={r.channel} severity={r.ok ? 'success' : 'error'} data-testid="settings-test-result">
                                {r.ok ? `Sent to ${r.address}. Check that it arrived.`
                                    : `${r.channel === 'email' ? 'Email' : 'Matrix'}: ${r.error}`}
                            </Alert>
                        ))}
                    </Stack>
                )}
            </Paper>

            <Paper sx={{ p: 3 }}>
                <Typography variant="h6">What to tell you about</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    Only about things that concern your own containers. Announcements to everyone, and messages to
                    a group you are in, always reach you on the channels above.
                </Typography>
                {TOPICS.map(topic => (
                    <Stack key={topic.key} direction="row" spacing={2} alignItems="center" sx={{ py: 1 }}>
                        <Box sx={{ color: 'action.active', display: 'flex' }}>{topic.icon}</Box>
                        <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                                <Typography variant="body1">{topic.title}</Typography>
                                {topic.protects &&
                                    <Chip size="small" label="Protects your data" color="primary" variant="outlined" />}
                            </Stack>
                            <Typography variant="body2" color="text.secondary">{topic.text(view.reminder_days)}</Typography>
                        </Box>
                        <Switch checked={view.topics[topic.key]} disabled={busy}
                                onChange={e => run('put', URL, { topics: { [topic.key]: e.target.checked } })}
                                slotProps={{ input: { 'aria-label': topic.title, 'data-testid': `settings-topic-${topic.key}` } }} />
                    </Stack>
                ))}
            </Paper>

            <RiskDialog open={Boolean(risk)} allOff={risk?.allOff} busy={busy}
                        onKeep={() => setRisk(null)} onConfirm={confirmRisk} />
        </Stack>
    );
}

export default NotificationSettings;
