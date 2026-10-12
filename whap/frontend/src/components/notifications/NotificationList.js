import React from 'react';
import {
    Box, Button, Chip, CircularProgress, IconButton, Paper, Stack, Table, TableBody, TableCell, TableHead,
    TableRow, Tooltip, Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ScheduleIcon from '@mui/icons-material/Schedule';
import EditIcon from '@mui/icons-material/Edit';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import BlockIcon from '@mui/icons-material/Block';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import { KindChip, formatTime } from './shared';

export function StatusChips({ notification }) {
    const { status, deliveries: d } = notification;
    if (status === 'draft') return <Chip size="small" icon={<EditIcon />} label="Draft" />;
    if (status === 'scheduled') return <Chip size="small" icon={<ScheduleIcon />} label="Scheduled" color="primary" />;
    if (status === 'cancelled') return <Chip size="small" icon={<BlockIcon />} label="Cancelled" />;
    return (
        <Stack direction="row" spacing={1}>
            {d.sent > 0 && <Chip size="small" icon={<CheckCircleIcon />} label={`${d.sent} delivered`}
                                 color="success" variant="outlined" />}
            {d.pending > 0 && <Chip size="small" icon={<HourglassEmptyIcon />} label={`${d.pending} sending`} />}
            {d.failed > 0 && <Chip size="small" icon={<ErrorOutlineIcon />} label={`${d.failed} failed`} color="error" />}
            {d.sent + d.pending + d.failed === 0 && <Chip size="small" label="Reached nobody" />}
        </Stack>
    );
}

function when(n, timeZone) {
    if (n.status === 'draft') return `Edited ${formatTime(n.updated_at, timeZone)}`;
    if (n.status === 'scheduled') {
        return `Sends ${formatTime(n.send_at, timeZone)}${n.remind_at ? ` · reminder ${formatTime(n.remind_at, timeZone)}` : ''}`;
    }
    if (n.status === 'cancelled') return `Cancelled · was for ${formatTime(n.send_at, timeZone)}`;
    return `Sent ${formatTime(n.sent_at, timeZone)}`;
}

/** Every notification admins have written, newest first. */
function NotificationList({ notifications, loading, timeZone, onNew, onOpen, onFollowUp }) {
    return (
        <>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
                <Typography variant="h6">Notifications</Typography>
                <Button variant="contained" startIcon={<AddIcon />} onClick={onNew} data-testid="notif-new">
                    New notification</Button>
            </Stack>
            <Paper>
                {loading ? <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}><CircularProgress /></Box>
                    : notifications.length === 0
                        ? <Typography sx={{ p: 3, color: 'text.secondary', textAlign: 'center' }}>
                            No notifications yet. Start one with "New notification".</Typography>
                        : (
                            <Table size="small">
                                <TableHead>
                                    <TableRow>
                                        <TableCell>Subject</TableCell>
                                        <TableCell>Type</TableCell>
                                        <TableCell>About</TableCell>
                                        <TableCell align="right">Recipients</TableCell>
                                        <TableCell>Status</TableCell>
                                        <TableCell>When</TableCell>
                                        <TableCell />
                                    </TableRow>
                                </TableHead>
                                <TableBody>
                                    {notifications.map(n => (
                                        <TableRow key={n.id} hover sx={{ cursor: 'pointer' }} onClick={() => onOpen(n)}
                                                  data-testid="notif-row" data-status={n.status}>
                                            <TableCell sx={{ fontWeight: 500 }}>
                                                {n.title || <i style={{ color: '#888' }}>No subject yet</i>}</TableCell>
                                            <TableCell><KindChip kind={n.kind} /></TableCell>
                                            <TableCell><code>{n.about}</code></TableCell>
                                            <TableCell align="right">
                                                {['sending', 'sent'].includes(n.status) ? n.recipients : '—'}</TableCell>
                                            <TableCell><StatusChips notification={n} /></TableCell>
                                            <TableCell sx={{ color: 'text.secondary', whiteSpace: 'nowrap' }}>
                                                {when(n, timeZone)}</TableCell>
                                            <TableCell align="right" onClick={e => e.stopPropagation()}>
                                                {n.status === 'sent' ? (
                                                    <Tooltip title="Follow up with the same people">
                                                        <IconButton size="small" onClick={() => onFollowUp(n)}>
                                                            <ContentCopyIcon fontSize="small" /></IconButton>
                                                    </Tooltip>
                                                ) : n.editable && (
                                                    <IconButton size="small" onClick={() => onOpen(n)} aria-label="Edit">
                                                        <EditIcon fontSize="small" /></IconButton>
                                                )}
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        )}
            </Paper>
        </>
    );
}

export default NotificationList;
