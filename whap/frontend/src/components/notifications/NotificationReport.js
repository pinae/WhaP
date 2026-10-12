import React, { useCallback, useEffect, useState } from 'react';
import {
    Alert, Box, Button, CircularProgress, IconButton, Paper, Stack, Table, TableBody, TableCell, TableHead,
    TableRow, Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import EmailIcon from '@mui/icons-material/Email';
import ChatIcon from '@mui/icons-material/Chat';
import ReplayIcon from '@mui/icons-material/Replay';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import DeleteIcon from '@mui/icons-material/Delete';
import api from '../../services/api';
import { API, KindChip, formatTime } from './shared';
import { StatusChips } from './NotificationList';

function DeliveryStatus({ delivery, timeZone }) {
    if (delivery.status === 'sent') {
        return <Typography variant="body2" color="success.main">
            Delivered {formatTime(delivery.sent_at, timeZone)}</Typography>;
    }
    if (delivery.status === 'pending') {
        return <Typography variant="body2" color="text.secondary">
            {delivery.attempts ? `Trying again (${delivery.attempts} tries so far)` : 'Waiting to be sent'}
            {delivery.last_error && <Typography variant="caption" display="block">{delivery.last_error}</Typography>}
        </Typography>;
    }
    return (
        <>
            <Typography variant="body2" color="error.main">Failed after {delivery.attempts}
                {delivery.attempts === 1 ? ' try' : ' tries'}</Typography>
            <Typography variant="caption" color="text.secondary">{delivery.last_error}</Typography>
        </>
    );
}

/** A sent (or cancelled) notification: who got it, what failed, what next. */
function NotificationReport({ id, timeZone, onBack, onOpenDraft }) {
    const [notification, setNotification] = useState(null);
    const [deliveries, setDeliveries] = useState([]);
    const [error, setError] = useState('');

    const load = useCallback(async () => {
        try {
            const [n, d] = await Promise.all([api.get(`${API}/${id}`), api.get(`${API}/${id}/deliveries`)]);
            setNotification(n.data);
            setDeliveries(d.data);
        } catch (err) {
            setError(err.response?.data?.message || 'Could not load the notification.');
        }
    }, [id]);

    useEffect(() => { load(); }, [load]);
    // Follow the queue while messages are still on their way.
    useEffect(() => {
        if (!notification || !(notification.deliveries.pending > 0 || notification.status === 'sending')) return undefined;
        const timer = setInterval(load, 5000);
        return () => clearInterval(timer);
    }, [notification, load]);

    const act = async (request, then) => {
        setError('');
        try {
            const response = await request();
            then(response);
        } catch (err) {
            setError(err.response?.data?.message || 'That did not work.');
        }
    };

    if (!notification) {
        return error ? <Alert severity="error">{error}</Alert>
            : <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}><CircularProgress /></Box>;
    }
    const { deliveries: counts } = notification;
    const copy = (followUp) => act(() => api.post(`${API}/${id}/copy`, { follow_up: followUp }),
        r => onOpenDraft(r.data.id));

    return (
        <>
            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }} flexWrap="wrap" useFlexGap>
                <IconButton size="small" onClick={onBack} aria-label="Back"><ArrowBackIcon /></IconButton>
                <Typography variant="h6" sx={{ flexGrow: 1 }} data-testid="report-subject">{notification.title}</Typography>
                {notification.status === 'cancelled' && (
                    <Button color="error" startIcon={<DeleteIcon />}
                            onClick={() => act(() => api.delete(`${API}/${id}`), onBack)}>Delete</Button>)}
                <Button onClick={() => copy(false)}>Copy</Button>
                {notification.status === 'sent' && (
                    <Button variant="outlined" startIcon={<ContentCopyIcon />} onClick={() => copy(true)}
                            data-testid="report-follow-up">Follow up with the same people</Button>)}
            </Stack>
            {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '8fr 4fr' }, gap: 3, alignItems: 'start' }}>
                <Paper>
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ p: 2 }}>
                        <StatusChips notification={notification} />
                        <Box sx={{ flexGrow: 1 }} />
                        {counts.failed > 0 && (
                            <Button startIcon={<ReplayIcon />} variant="contained" color="error" size="small"
                                    data-testid="report-retry"
                                    onClick={() => act(() => api.post(`${API}/${id}/retry`), load)}>
                                Retry {counts.failed} failed</Button>)}
                    </Stack>
                    {deliveries.length === 0 ? (
                        <Typography sx={{ p: 2, pt: 0 }} color="text.secondary">
                            {notification.status === 'cancelled' ? 'Cancelled before it was sent.'
                                : 'Nobody it concerned could be reached.'}</Typography>
                    ) : (
                        <Table size="small">
                            <TableHead>
                                <TableRow><TableCell>User</TableCell><TableCell>Channel</TableCell>
                                    <TableCell>Address</TableCell><TableCell>Status</TableCell></TableRow>
                            </TableHead>
                            <TableBody>
                                {deliveries.map(d => (
                                    <TableRow key={d.id} data-testid="report-delivery" data-status={d.status}>
                                        <TableCell>{d.username}{d.phase === 'reminder' &&
                                            <Typography variant="caption" color="text.secondary"> (reminder)</Typography>}
                                        </TableCell>
                                        <TableCell>{d.channel === 'email'
                                            ? <EmailIcon fontSize="small" color="action" titleAccess="Email" />
                                            : <ChatIcon fontSize="small" color="action" titleAccess="Matrix" />}</TableCell>
                                        <TableCell>{d.address}</TableCell>
                                        <TableCell><DeliveryStatus delivery={d} timeZone={timeZone} /></TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    )}
                </Paper>
                <Paper sx={{ p: 2 }}>
                    <Stack spacing={1.5}>
                        <Box><KindChip kind={notification.kind} /></Box>
                        <Box>
                            <Typography variant="overline" color="text.secondary">About</Typography>
                            <Typography variant="body2"><code>{notification.about}</code></Typography>
                        </Box>
                        <Box>
                            <Typography variant="overline" color="text.secondary">
                                {notification.status === 'cancelled' ? 'Was scheduled for' : 'Sent'}</Typography>
                            <Typography variant="body2">
                                {formatTime(notification.sent_at || notification.send_at, timeZone)}
                                {notification.remind_at && ` · reminder ${formatTime(notification.remind_at, timeZone)}`}
                            </Typography>
                        </Box>
                        <Box>
                            <Typography variant="overline" color="text.secondary">Message</Typography>
                            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>{notification.body}</Typography>
                        </Box>
                    </Stack>
                </Paper>
            </Box>
        </>
    );
}

export default NotificationReport;
