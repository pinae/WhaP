import React, { useEffect, useState } from 'react';
import {
    Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Divider, Paper, Stack, Table, TableBody,
    TableCell, TableHead, TableRow, Typography,
} from '@mui/material';
import HourglassBottomIcon from '@mui/icons-material/HourglassBottom';
import api from '../../services/api';
import { daysBefore } from '../NotificationSettings';
import { API, formatTime } from './shared';
import { StatusChips } from './NotificationList';

/** The automatic expiry reminders: when they go out, which are next, which went out. */
function ExpiryOverview({ timeZone, onOpen }) {
    const [overview, setOverview] = useState(null);
    const [preview, setPreview] = useState(null);

    useEffect(() => {
        api.get(`${API}/expiry`).then(r => setOverview(r.data)).catch(() => {});
    }, []);

    const showPreview = () => api.get(`${API}/expiry/preview`).then(r => setPreview(r.data)).catch(() => {});

    if (!overview) return null;
    return (
        <>
            <Typography variant="h6" sx={{ mt: 4, mb: 1 }}>Automatic reminders</Typography>
            <Paper sx={{ p: 2 }} data-testid="expiry-overview">
                <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1 }}>
                    <HourglassBottomIcon color="action" />
                    <Box sx={{ flexGrow: 1 }}>
                        <Typography variant="subtitle1">Expiry of local containers</Typography>
                        <Typography variant="body2" color="text.secondary">
                            Sent {daysBefore(overview.days)} a <code>worker_local_</code> container's ttl date, with
                            a link to prolong it. Set in the deployment (<code>whap.notifications.ttl_reminder_days</code>).
                        </Typography>
                    </Box>
                    <Button variant="outlined" size="small" onClick={showPreview} data-testid="expiry-preview"
                            sx={{ whiteSpace: 'nowrap', flexShrink: 0 }}>
                        Preview message</Button>
                </Stack>
                <Divider sx={{ my: 1 }} />
                <Typography variant="body2" color="text.secondary" sx={{ my: 1 }}>Next 7 days</Typography>
                {overview.upcoming.length === 0
                    ? <Typography variant="body2" sx={{ mb: 1 }}>No reminders due.</Typography>
                    : (
                        <Table size="small">
                            <TableHead>
                                <TableRow><TableCell>User</TableCell><TableCell>Project</TableCell>
                                    <TableCell>Server</TableCell><TableCell>Expires</TableCell>
                                    <TableCell>Reminder</TableCell><TableCell>Sends</TableCell></TableRow>
                            </TableHead>
                            <TableBody>
                                {overview.upcoming.map(r => (
                                    <TableRow key={`${r.container_id}-${r.step}`} data-testid="expiry-upcoming">
                                        <TableCell>{r.user}</TableCell><TableCell>{r.project}</TableCell>
                                        <TableCell>{r.server}</TableCell>
                                        <TableCell>{formatTime(r.ttl_date, timeZone).split(',')[0]}</TableCell>
                                        <TableCell>{r.step === 1 ? '1 day before' : `${r.step} days before`}</TableCell>
                                        <TableCell>{formatTime(r.sends_at, timeZone)}</TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    )}
                <Typography variant="body2" color="text.secondary" sx={{ mt: 2, mb: 1 }}>Sent in the last 7 days</Typography>
                {overview.recent.length === 0
                    ? <Typography variant="body2">None.</Typography>
                    : (
                        <Table size="small">
                            <TableBody>
                                {overview.recent.map(n => (
                                    <TableRow key={n.id} hover sx={{ cursor: 'pointer' }} onClick={() => onOpen(n)}
                                              data-testid="expiry-recent">
                                        <TableCell>{n.title}</TableCell>
                                        <TableCell><StatusChips notification={n} /></TableCell>
                                        <TableCell sx={{ color: 'text.secondary' }}>{formatTime(n.sent_at || n.send_at, timeZone)}</TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    )}
            </Paper>
            <Dialog open={Boolean(preview)} onClose={() => setPreview(null)} maxWidth="md" fullWidth>
                <DialogTitle>The expiry reminder</DialogTitle>
                <DialogContent>
                    {preview && (preview.sample ? (
                        <>
                            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                                As {preview.username}, whose container expires next, would get it now.</Typography>
                            <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1 }}>
                                <Typography variant="subtitle2" sx={{ px: 2, py: 1, bgcolor: 'grey.50' }}>{preview.subject}</Typography>
                                {/* Rendered and escaped by the backend, as it is sent. */}
                                <Box sx={{ p: 2, fontSize: 14 }} dangerouslySetInnerHTML={{ __html: preview.html }} />
                            </Box>
                        </>
                    ) : (
                        <>
                            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                                No local container expires soon, so here is the template.</Typography>
                            <Typography variant="subtitle2">{preview.subject}</Typography>
                            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', mt: 1 }}>{preview.text}</Typography>
                        </>
                    ))}
                </DialogContent>
                <DialogActions><Button onClick={() => setPreview(null)}>Close</Button></DialogActions>
            </Dialog>
        </>
    );
}

export default ExpiryOverview;
