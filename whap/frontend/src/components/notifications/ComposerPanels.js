import React, { useState } from 'react';
import {
    Alert, Box, Button, Card, CardContent, Checkbox, Chip, CircularProgress, Dialog, DialogActions, DialogContent,
    DialogTitle, FormControlLabel, IconButton, Link, Stack, Tab, Table, TableBody, TableCell, TableHead, TableRow,
    Tabs, Typography,
} from '@mui/material';
import EmailIcon from '@mui/icons-material/Email';
import ChatIcon from '@mui/icons-material/Chat';
import NotificationsOffIcon from '@mui/icons-material/NotificationsOff';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import ScheduleIcon from '@mui/icons-material/Schedule';
import SendIcon from '@mui/icons-material/Send';
import { UNREACHABLE, names } from './shared';

const unreached = (summary) => Object.values(summary.unreachable).reduce((a, b) => a + b, 0);

export function describeAudience(kind, params, options) {
    if (kind === 'maintenance') {
        const hosts = options.servers.filter(s => (params.server_ids || []).includes(s.id)).map(s => s.hostname);
        return <>users with containers on <b>{hosts.join(', ')}</b></>;
    }
    if (kind === 'image') return <>users of <b>{params.image}</b></>;
    if (kind === 'dataset') return <>users mounting <b>{params.dataset}</b></>;
    if (kind === 'group') {
        const groups = options.groups.filter(g => (params.group_ids || []).includes(g.id)).map(g => g.name);
        return <>members of <b>{groups.join(', ')}</b></>;
    }
    return <>WhaP users</>;
}

/** How many people it reaches, and how. */
export function AudienceCard({ audience, description, onShowAll }) {
    const { data, error, loading } = audience;
    return (
        <Card variant="outlined" data-testid="audience-card">
            <CardContent>
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Typography variant="overline" color="text.secondary">Recipients</Typography>
                    {loading && <CircularProgress size={16} />}
                </Stack>
                {error ? <Typography variant="body2" color="text.secondary" data-testid="audience-hint">{error}</Typography>
                    : data && (
                    <>
                        <Stack direction="row" alignItems="baseline" spacing={1}>
                            <Typography variant="h3" sx={{ fontWeight: 500 }} data-testid="audience-count">
                                {data.summary.reached}</Typography>
                            <Typography variant="body1">{description}</Typography>
                        </Stack>
                        <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: 'wrap', rowGap: 1 }}>
                            <Chip size="small" icon={<EmailIcon />} label={`${data.summary.email} by email`} />
                            {data.summary.matrix > 0 &&
                                <Chip size="small" icon={<ChatIcon />} label={`${data.summary.matrix} on Matrix`} />}
                            {unreached(data.summary) > 0 &&
                                <Chip size="small" icon={<NotificationsOffIcon />} color="warning" variant="outlined"
                                      label={`${unreached(data.summary)} won't be notified`} />}
                        </Stack>
                        {data.summary.total > 0 && (
                            <Link component="button" variant="body2" sx={{ mt: 1.5, display: 'block' }}
                                  onClick={onShowAll} data-testid="audience-show-all">
                                Show all {data.summary.total} {data.summary.total === 1 ? 'user' : 'users'}</Link>)}
                    </>
                )}
            </CardContent>
        </Card>
    );
}

function ReachedBy({ recipient }) {
    if (recipient.unreachable) {
        return <Chip size="small" variant="outlined" color={recipient.unreachable === 'no_address' ? 'error' : 'warning'}
                     icon={recipient.unreachable === 'no_address' ? <ErrorOutlineIcon /> : <NotificationsOffIcon />}
                     label={UNREACHABLE[recipient.unreachable]} />;
    }
    return (
        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
            {recipient.channels.map(c => <Chip key={c.channel} size="small" label={c.address}
                                               icon={c.channel === 'email' ? <EmailIcon /> : <ChatIcon />} />)}
        </Stack>
    );
}

/** Everyone it concerns, highlighting those it won't reach. */
export function AudienceDialog({ open, onClose, recipients, subject }) {
    const [onlyMissed, setOnlyMissed] = useState(false);
    const shown = onlyMissed ? recipients.filter(r => r.unreachable) : recipients;
    return (
        <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth data-testid="audience-dialog">
            <DialogTitle>Who gets {subject ? `“${subject}”` : 'this notification'}</DialogTitle>
            <DialogContent>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    As of now. The list is worked out again when the notification is sent, so containers created
                    until then are included.
                </Typography>
                <Table size="small">
                    <TableHead>
                        <TableRow><TableCell>User</TableCell><TableCell>Their containers</TableCell>
                            <TableCell>Reached by</TableCell></TableRow>
                    </TableHead>
                    <TableBody>
                        {shown.map(r => (
                            <TableRow key={r.user_uid} sx={r.unreachable ? { bgcolor: 'rgba(237,108,2,0.06)' } : undefined}>
                                <TableCell><b>{r.username}</b>
                                    {r.name !== r.username &&
                                        <Typography variant="caption" display="block" color="text.secondary">{r.name}</Typography>}
                                </TableCell>
                                <TableCell>{r.containers.length === 0 ? '—' : r.containers.map(c => (
                                    <Typography key={c.id} variant="body2">{c.project} ({c.image}) on {c.server}</Typography>))}
                                </TableCell>
                                <TableCell><ReachedBy recipient={r} /></TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </DialogContent>
            <DialogActions>
                <FormControlLabel sx={{ mr: 'auto', ml: 1 }} label="Only users who won't be notified"
                                  control={<Checkbox size="small" checked={onlyMissed}
                                                     onChange={e => setOnlyMissed(e.target.checked)} />} />
                <Button variant="contained" onClick={onClose}>Close</Button>
            </DialogActions>
        </Dialog>
    );
}

/** The message as one recipient reads it, by email or on Matrix. */
export function PreviewCard({ preview, onStep }) {
    const [tab, setTab] = useState('email');
    const { data, loading } = preview;
    const list = data?.recipients || [];
    const index = data ? list.findIndex(r => r.user_uid === data.user_uid) : -1;
    return (
        <Card variant="outlined" data-testid="preview-card">
            <CardContent>
                <Stack direction="row" alignItems="center" justifyContent="space-between">
                    <Typography variant="overline" color="text.secondary">Preview</Typography>
                    {data && (
                        <Stack direction="row" alignItems="center">
                            {loading && <CircularProgress size={14} sx={{ mr: 1 }} />}
                            <IconButton size="small" disabled={index <= 0} onClick={() => onStep(list[index - 1].user_uid)}
                                        aria-label="Previous recipient"><ChevronLeftIcon /></IconButton>
                            <Typography variant="body2" data-testid="preview-recipient">
                                {data.username}{index >= 0 ? ` · ${index + 1} of ${list.length}` : ' (nobody else yet)'}
                            </Typography>
                            <IconButton size="small" disabled={index < 0 || index >= list.length - 1}
                                        onClick={() => onStep(list[index + 1].user_uid)}
                                        aria-label="Next recipient"><ChevronRightIcon /></IconButton>
                        </Stack>
                    )}
                </Stack>
                <Tabs value={tab} onChange={(e, v) => setTab(v)} sx={{ minHeight: 36, mb: 1 }}>
                    <Tab value="email" label="Email" icon={<EmailIcon fontSize="small" />} iconPosition="start" sx={{ minHeight: 36 }} />
                    <Tab value="matrix" label="Matrix" icon={<ChatIcon fontSize="small" />} iconPosition="start" sx={{ minHeight: 36 }} />
                </Tabs>
                {!data ? <Typography variant="body2" color="text.secondary">
                    {preview.error || 'The message appears here once there is something to show.'}</Typography>
                    : (
                    <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1, bgcolor: 'background.paper' }}
                         data-testid={`preview-${tab}`}>
                        {tab === 'email' && (
                            <Box sx={{ px: 2, py: 1, bgcolor: 'grey.50', borderBottom: 1, borderColor: 'divider' }}>
                                <Typography variant="caption" display="block" color="text.secondary">
                                    To: {data.email.to || '(no address)'}</Typography>
                                <Typography variant="subtitle2">{data.email.subject}</Typography>
                            </Box>
                        )}
                        {/* Rendered and escaped by the backend, as it is sent. */}
                        <Box sx={{ p: 2, fontSize: 14, '& p': { mt: 0 }, '& hr': { borderColor: 'divider' } }}
                             dangerouslySetInnerHTML={{ __html: tab === 'email' ? data.email.html : data.matrix.html }} />
                    </Box>
                )}
            </CardContent>
        </Card>
    );
}

/** The one confirmation: when, how, who won't hear about it. */
export function ConfirmDialog({ open, onClose, onConfirm, busy, subject, audience, when }) {
    if (!audience) return null;
    const { summary, recipients } = audience;
    const missed = recipients.filter(r => r.unreachable);
    const now = !when;
    const action = `${now ? 'Send to' : 'Schedule for'} ${summary.reached} ${summary.reached === 1 ? 'user' : 'users'}`;
    return (
        <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth data-testid="confirm-dialog">
            <DialogTitle>{now ? 'Send' : 'Schedule'} “{subject}” {now ? 'to' : 'for'} {summary.reached}
                {summary.reached === 1 ? ' user' : ' users'}?</DialogTitle>
            <DialogContent>
                <Typography variant="body2" sx={{ mb: 2 }}>
                    {now ? 'WhaP sends it right away' : <>WhaP sends it on <b>{when.send}</b></>}
                    {when?.remind && <> and a reminder on <b>{when.remind}</b></>}:
                    {' '}{summary.email} {summary.email === 1 ? 'email' : 'emails'}
                    {summary.matrix > 0 && ` and ${summary.matrix} Matrix ${summary.matrix === 1 ? 'message' : 'messages'}`}.
                    {now ? ' Once sent, it can\'t be recalled.'
                        : ' You can still edit or cancel it until then; once it has gone out it can\'t be recalled.'}
                </Typography>
                {missed.length > 0 && (
                    <Alert severity="warning" icon={<NotificationsOffIcon />}>
                        <b>{missed.length} {missed.length === 1 ? 'user won\'t' : 'users won\'t'} hear about it:</b>{' '}
                        {names(missed.map(r => `${r.username} (${UNREACHABLE[r.unreachable].toLowerCase()})`))}.
                    </Alert>
                )}
            </DialogContent>
            <DialogActions>
                <Button onClick={onClose} disabled={busy}>Back to editing</Button>
                <Button variant="contained" onClick={onConfirm} disabled={busy} data-testid="confirm-send"
                        endIcon={now ? <SendIcon /> : <ScheduleIcon />}>{action}</Button>
            </DialogActions>
        </Dialog>
    );
}
