import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    Alert, Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogContentText,
    DialogTitle, FormControl, FormControlLabel, IconButton, InputLabel, Link, MenuItem, OutlinedInput, Paper,
    Radio, RadioGroup, Select, Stack, TextField, ToggleButton, ToggleButtonGroup, Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import SendIcon from '@mui/icons-material/Send';
import api from '../../services/api';
import { API, COMPOSABLE, KINDS, formatTime, shiftLocal, toLocalInput } from './shared';
import { AudienceCard, AudienceDialog, ConfirmDialog, PreviewCard, describeAudience } from './ComposerPanels';

const EMPTY_PARAMS = { server_ids: [], start: '', end: '', impact: 'stopped', image: '', dataset: '', group_ids: [] };

const IMPACT_LABELS = {
    stopped: 'They are stopped; users start them again afterwards',
    restarted: 'They restart by themselves; running processes are lost',
    none: 'Nothing; only performance is affected',
};

export function paramsFor(kind, p) {
    switch (kind) {
        case 'maintenance': return { server_ids: p.server_ids, start: p.start, end: p.end, impact: p.impact };
        case 'image': return { image: p.image };
        case 'dataset': return { dataset: p.dataset };
        case 'group': return { group_ids: p.group_ids };
        default: return {};
    }
}

/** send_at/remind_at for a schedule choice; local times, read by the server in its zone. */
export function scheduleTimes(schedule, kind, params) {
    if (schedule.mode === 'day_before' && kind === 'maintenance' && params.start) {
        return { send_at: shiftLocal(params.start, -24), remind_at: shiftLocal(params.start, -1) };
    }
    if (schedule.mode === 'at') return { send_at: schedule.sendAt || null, remind_at: schedule.remindAt || null };
    return { send_at: null, remind_at: null };
}

/** A time from the server ("…Z") or the form (already local) as text in the server's zone. */
function shown(value, timeZone) {
    if (!value) return '';
    return /[zZ]|[+-]\d\d:\d\d$/.test(value) ? formatTime(value, timeZone) : formatTime(`${value}:00Z`, 'UTC');
}

function useDebounced(value, delay) {
    const [debounced, setDebounced] = useState(value);
    useEffect(() => {
        const timer = setTimeout(() => setDebounced(value), delay);
        return () => clearTimeout(timer);
    }, [value, delay]);
    return debounced;
}

function KindFields({ kind, params, set, options }) {
    if (kind === 'maintenance') {
        return (
            <Stack spacing={2}>
                <FormControl fullWidth size="small">
                    <InputLabel id="servers-label">Servers</InputLabel>
                    <Select labelId="servers-label" multiple value={params.server_ids} input={<OutlinedInput label="Servers" />}
                            onChange={e => set({ server_ids: e.target.value })} data-testid="composer-servers"
                            renderValue={ids => <Stack direction="row" spacing={0.5}>
                                {ids.map(id => <Chip key={id} size="small"
                                                     label={options.servers.find(s => s.id === id)?.hostname} />)}</Stack>}>
                        {options.servers.map(s => <MenuItem key={s.id} value={s.id}
                                                            data-testid={`composer-server-${s.hostname}`}>
                            {s.hostname} · {s.containers} {s.containers === 1 ? 'container' : 'containers'}</MenuItem>)}
                    </Select>
                </FormControl>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                    <TextField size="small" label="Starts" type="datetime-local" value={params.start} sx={{ flex: 1 }}
                               onChange={e => set({ start: e.target.value, end: params.end || shiftLocal(e.target.value, 1) })}
                               slotProps={{ inputLabel: { shrink: true }, htmlInput: { 'data-testid': 'composer-start' } }} />
                    <TextField size="small" label="Ends" type="datetime-local" value={params.end} sx={{ flex: 1 }}
                               onChange={e => set({ end: e.target.value })}
                               slotProps={{ inputLabel: { shrink: true }, htmlInput: { 'data-testid': 'composer-end' } }} />
                </Stack>
                <Typography variant="caption" color="text.secondary" sx={{ mt: '4px !important' }}>
                    Times are in {options.timezone}.</Typography>
                <Box>
                    <Typography variant="body2" sx={{ mb: 0.5 }}>What happens to running containers?</Typography>
                    <RadioGroup value={params.impact} onChange={e => set({ impact: e.target.value })}>
                        {Object.entries(IMPACT_LABELS).map(([value, label]) => (
                            <FormControlLabel key={value} value={value} control={<Radio size="small" />} label={label} />))}
                    </RadioGroup>
                </Box>
            </Stack>
        );
    }
    if (kind === 'image' || kind === 'dataset') {
        const choices = kind === 'image' ? options.images : options.datasets;
        return (
            <FormControl fullWidth size="small">
                <InputLabel id={`${kind}-label`}>{kind === 'image' ? 'Image' : 'Dataset'}</InputLabel>
                <Select labelId={`${kind}-label`} label={kind === 'image' ? 'Image' : 'Dataset'} value={params[kind]}
                        onChange={e => set({ [kind]: e.target.value })} data-testid={`composer-${kind}`}>
                    {choices.map(c => <MenuItem key={c.name} value={c.name}>
                        {c.name} · {c.containers} {c.containers === 1 ? 'container' : 'containers'}</MenuItem>)}
                </Select>
            </FormControl>
        );
    }
    if (kind === 'group') {
        return (
            <FormControl fullWidth size="small">
                <InputLabel id="groups-label">Groups</InputLabel>
                <Select labelId="groups-label" multiple value={params.group_ids} input={<OutlinedInput label="Groups" />}
                        onChange={e => set({ group_ids: e.target.value })} data-testid="composer-groups"
                        renderValue={ids => <Stack direction="row" spacing={0.5}>
                            {ids.map(id => <Chip key={id} size="small" label={options.groups.find(g => g.id === id)?.name} />)}
                        </Stack>}>
                    {options.groups.map(g => <MenuItem key={g.id} value={g.id} data-testid={`composer-group-${g.name}`}>
                        {g.name} · {g.members} {g.members === 1 ? 'member' : 'members'}</MenuItem>)}
                </Select>
            </FormControl>
        );
    }
    return <Typography variant="body2" color="text.secondary">
        Goes to everyone with a WhaP account, whatever topics they switched off.</Typography>;
}

/** Write a notification: what about, the message, who gets it, as they will read it. */
function NotificationComposer({ id, options, onBack, onDone }) {
    const [draftId, setDraftId] = useState(id);
    const [status, setStatus] = useState(id ? null : 'draft');
    const [form, setForm] = useState({ kind: 'maintenance', subject: options.templates.maintenance.subject,
                                       body: options.templates.maintenance.body, params: EMPTY_PARAMS });
    const [schedule, setSchedule] = useState({ mode: 'day_before', sendAt: '', remindAt: '' });
    const [loaded, setLoaded] = useState(!id);
    const [saved, setSaved] = useState(null);  // when the draft was last saved
    const [audience, setAudience] = useState({ data: null, error: '', loading: false });
    const [preview, setPreview] = useState({ data: null, error: '', loading: false });
    const [previewUser, setPreviewUser] = useState(null);
    const [dialog, setDialog] = useState(null);  // 'audience' | 'confirm' | 'discard' | 'cancel'
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [testResults, setTestResults] = useState(null);
    const bodyRef = useRef(null);
    const zone = options.timezone;

    // Load an existing draft or scheduled notification.
    useEffect(() => {
        if (!id) return;
        api.get(`${API}/${id}`).then(({ data }) => {
            const p = data.params || {};
            setForm({ kind: data.kind, subject: data.subject, body: data.body, params: {
                ...EMPTY_PARAMS, ...p, start: toLocalInput(p.start, zone), end: toLocalInput(p.end, zone) } });
            setStatus(data.status);
            if (data.send_at && data.status === 'scheduled') {
                setSchedule({ mode: 'at', sendAt: toLocalInput(data.send_at, zone),
                              remindAt: toLocalInput(data.remind_at, zone) });
            } else if (data.kind !== 'maintenance') {
                setSchedule(s => ({ ...s, mode: 'now' }));
            }
            setSaved(data.updated_at);
            setLoaded(true);
        }).catch(err => setError(err.response?.data?.message || 'Could not load the notification.'));
    }, [id, zone]);

    const params = useMemo(() => paramsFor(form.kind, form.params), [form.kind, form.params]);
    const request = useMemo(() => ({ kind: form.kind, params, subject: form.subject, body: form.body }),
        [form.kind, params, form.subject, form.body]);
    // null until a stored notification has loaded, so nothing is asked about the empty form.
    const debouncedAudienceKey = useDebounced(loaded ? JSON.stringify({ kind: form.kind, params }) : null, 400);
    const debouncedPreviewKey = useDebounced(loaded ? JSON.stringify({ ...request, user_uid: previewUser }) : null, 500);
    const debouncedForm = useDebounced(form, 1200);

    // Who gets it, whenever what it is about changes.
    useEffect(() => {
        if (!debouncedAudienceKey) return undefined;
        let current = true;
        setAudience(a => ({ ...a, loading: true }));
        api.post(`${API}/audience`, JSON.parse(debouncedAudienceKey))
            .then(r => current && setAudience({ data: r.data, error: '', loading: false }))
            .catch(err => current && setAudience({ data: null, loading: false,
                error: err.response?.data?.message || 'Could not work out who gets this.' }));
        return () => { current = false; };
    }, [debouncedAudienceKey]);

    // The message as one of them reads it.
    useEffect(() => {
        if (!debouncedPreviewKey) return undefined;
        let current = true;
        setPreview(p => ({ ...p, loading: true }));
        api.post(`${API}/preview`, JSON.parse(debouncedPreviewKey))
            .then(r => current && setPreview({ data: r.data, error: '', loading: false }))
            .catch(err => current && setPreview({ data: null, loading: false,
                error: err.response?.data?.message || 'No preview.' }));
        return () => { current = false; };
    }, [debouncedPreviewKey]);

    // One save at a time, so an autosave and "Review and send" can't create two drafts.
    const draftIdRef = useRef(id);
    const saving = useRef(Promise.resolve());
    const saveDraft = useCallback((f = form) => {
        const save = async () => {
            const body = { kind: f.kind, subject: f.subject, body: f.body, params: paramsFor(f.kind, f.params) };
            const response = draftIdRef.current ? await api.put(`${API}/${draftIdRef.current}`, body)
                : await api.post(API, body);
            draftIdRef.current = response.data.id;
            setDraftId(response.data.id);
            setSaved(response.data.updated_at);
            return response.data;
        };
        saving.current = saving.current.catch(() => {}).then(save);
        return saving.current;
    }, [form]);

    // Drafts save themselves once changed; scheduled ones only on "Save changes", as they must
    // stay complete. A new composer nobody has typed in saves nothing.
    const lastSaved = useRef(null);
    useEffect(() => {
        if (!loaded) return;
        const current = JSON.stringify(debouncedForm);
        if (lastSaved.current === null) { lastSaved.current = current; return; }
        if (status !== 'draft' || current === lastSaved.current) return;
        lastSaved.current = current;
        saveDraft(debouncedForm).catch(() => {});
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [debouncedForm, loaded]);

    const setParams = (changes) => setForm(f => ({ ...f, params: { ...f.params, ...changes } }));

    const changeKind = (kind) => {
        if (!kind) return;
        setForm(f => {
            const old = options.templates[f.kind];
            const fresh = options.templates[kind];
            // Keep what the admin wrote; replace what is still the old template.
            return { ...f, kind,
                     subject: !f.subject || f.subject === old.subject ? fresh.subject : f.subject,
                     body: !f.body.trim() || f.body === old.body ? fresh.body : f.body };
        });
        setSchedule(s => ({ ...s, mode: kind === 'maintenance' ? 'day_before' : (s.mode === 'day_before' ? 'now' : s.mode) }));
        setPreviewUser(null);
    };

    const insertField = (field) => {
        const input = bodyRef.current;
        const at = input ? input.selectionStart : form.body.length;
        const end = input ? input.selectionEnd : at;
        setForm(f => ({ ...f, body: `${f.body.slice(0, at)}{${field}}${f.body.slice(end)}` }));
        setTimeout(() => {
            if (input) { input.focus(); input.selectionStart = input.selectionEnd = at + field.length + 2; }
        });
    };

    const times = scheduleTimes(schedule, form.kind, form.params);
    const when = times.send_at ? { send: shown(times.send_at, zone), remind: times.remind_at && shown(times.remind_at, zone) }
        : null;
    const ready = form.subject.trim() && form.body.trim() && audience.data?.summary?.reached > 0;

    const run = async (action, then) => {
        setBusy(true);
        setError('');
        try {
            await then(await action());
        } catch (err) {
            setError(err.response?.data?.message || 'That did not work.');
        } finally {
            setBusy(false);
        }
    };

    const sendTest = () => run(() => api.post(`${API}/test`, { ...request, user_uid: previewUser }),
        r => setTestResults(r.data));

    const scheduleIt = () => run(async () => {
        const draft = await saveDraft();
        return api.post(`${API}/${draft.id}/schedule`, times);
    }, r => {
        setDialog(null);
        onDone(times.send_at ? `Scheduled “${r.data.subject}” for ${formatTime(r.data.send_at, zone)}.`
            : `Sending “${r.data.subject}” now.`);
    });

    const saveScheduled = () => run(() => api.put(`${API}/${draftId}`, { ...request, ...times }),
        () => onDone(`Saved the changes to “${form.subject}”.`));

    const discard = () => run(() => (draftId ? api.delete(`${API}/${draftId}`) : Promise.resolve()),
        () => onBack());

    const cancelScheduled = () => run(() => api.post(`${API}/${draftId}/cancel`),
        () => onDone(`Cancelled “${form.subject}”. Nobody gets it.`));

    if (!loaded) {
        return error ? <Alert severity="error">{error}</Alert>
            : <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}><CircularProgress /></Box>;
    }
    const fields = options.fields[form.kind] || [];

    return (
        <>
            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
                <IconButton size="small" onClick={onBack} aria-label="Back"><ArrowBackIcon /></IconButton>
                <Typography variant="h6">{status === 'scheduled' ? 'Scheduled notification' : 'New notification'}</Typography>
            </Stack>
            {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}
                             data-testid="composer-error">{error}</Alert>}
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '7fr 5fr' }, gap: 3, alignItems: 'start' }}>
                <Stack spacing={3} sx={{ minWidth: 0 }}>
                    <Paper sx={{ p: 2.5 }}>
                        <Typography variant="subtitle1" sx={{ mb: 1.5 }}>1. What is it about?</Typography>
                        <ToggleButtonGroup value={form.kind} exclusive fullWidth color="primary" size="small"
                                           onChange={(e, kind) => changeKind(kind)} disabled={status === 'scheduled'}
                                           sx={{ flexWrap: { xs: 'wrap', md: 'nowrap' } }}>
                            {COMPOSABLE.map(kind => (
                                <ToggleButton key={kind} value={kind} data-testid={`composer-kind-${kind}`}
                                              sx={{ textTransform: 'none', gap: 1, py: 1.2 }}>
                                    {KINDS[kind].icon}{KINDS[kind].label}</ToggleButton>))}
                        </ToggleButtonGroup>
                        <Box sx={{ mt: 2.5 }}>
                            <KindFields kind={form.kind} params={form.params} set={setParams} options={options} />
                        </Box>
                    </Paper>
                    <Paper sx={{ p: 2.5 }}>
                        <Typography variant="subtitle1" sx={{ mb: 0.5 }}>2. Message</Typography>
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                            Fields in braces are filled in for each person; the preview shows the result.
                        </Typography>
                        <Stack spacing={2}>
                            <TextField size="small" label="Subject" fullWidth value={form.subject}
                                       onChange={e => setForm(f => ({ ...f, subject: e.target.value }))}
                                       slotProps={{ htmlInput: { maxLength: 255, 'data-testid': 'composer-subject' } }} />
                            <TextField label="Message" fullWidth multiline minRows={12} value={form.body}
                                       inputRef={bodyRef} onChange={e => setForm(f => ({ ...f, body: e.target.value }))}
                                       slotProps={{ input: { sx: { fontSize: 14 } },
                                                    htmlInput: { 'data-testid': 'composer-body' } }} />
                            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                                <Typography variant="caption" color="text.secondary">Insert:</Typography>
                                {fields.map(f => <Chip key={f} size="small" label={`{${f}}`} variant="outlined"
                                                       onClick={() => insertField(f)} />)}
                                <Box sx={{ flexGrow: 1 }} />
                                <Link component="button" variant="caption" onClick={() => setForm(f => ({
                                    ...f, subject: options.templates[f.kind].subject, body: options.templates[f.kind].body }))}>
                                    Reset to the template</Link>
                            </Stack>
                        </Stack>
                    </Paper>
                </Stack>
                <Stack spacing={2} sx={{ position: { md: 'sticky' }, top: 16, minWidth: 0 }}>
                    <AudienceCard audience={audience} onShowAll={() => setDialog('audience')}
                                  description={describeAudience(form.kind, form.params, options)} />
                    <PreviewCard preview={preview} onStep={setPreviewUser} />
                </Stack>
            </Box>

            {testResults && (
                <Alert sx={{ mt: 2 }} onClose={() => setTestResults(null)} data-testid="composer-test-result"
                       severity={testResults.results.every(r => r.ok) ? 'success' : 'error'}>
                    Test written as for {testResults.as_user}:{' '}
                    {testResults.results.map(r => r.ok ? `sent to ${r.address}` : `${r.channel} failed: ${r.error}`).join('; ')}.
                </Alert>
            )}

            <Paper elevation={3} sx={{ position: 'sticky', bottom: 0, mt: 3, p: 1.5, display: 'flex', gap: 1,
                                       alignItems: 'center', flexWrap: 'wrap', zIndex: 2 }}>
                <Typography variant="body2" color="text.secondary" sx={{ flexGrow: 1, pl: 1 }} data-testid="composer-saved">
                    {status === 'scheduled' ? `Scheduled for ${shown(times.send_at || '', zone) || 'now'}`
                        : saved ? `Draft saved ${formatTime(saved, zone)}` : 'Not saved yet'}
                </Typography>
                {status === 'scheduled'
                    ? <Button color="error" onClick={() => setDialog('cancel')} disabled={busy}>Cancel notification</Button>
                    : <Button onClick={() => (draftId ? setDialog('discard') : onBack())} disabled={busy}>Discard</Button>}
                <Button variant="outlined" onClick={sendTest} disabled={busy || !form.subject.trim()}
                        data-testid="composer-test">Send a test to me</Button>
                <FormControl size="small" sx={{ minWidth: 230 }}>
                    <Select value={schedule.mode} onChange={e => setSchedule(s => ({ ...s, mode: e.target.value }))}
                            data-testid="composer-schedule">
                        <MenuItem value="now" data-testid="composer-when-now">Send now</MenuItem>
                        {form.kind === 'maintenance' &&
                            <MenuItem value="day_before" disabled={!form.params.start} data-testid="composer-when-day_before">
                                Send 1 day before, remind 1 h before</MenuItem>}
                        <MenuItem value="at" data-testid="composer-when-at">Send at…</MenuItem>
                    </Select>
                </FormControl>
                {schedule.mode === 'at' && (
                    <>
                        <TextField size="small" type="datetime-local" label="Send at" value={schedule.sendAt}
                                   onChange={e => setSchedule(s => ({ ...s, sendAt: e.target.value }))}
                                   slotProps={{ inputLabel: { shrink: true } }} />
                        <TextField size="small" type="datetime-local" label="Reminder (optional)" value={schedule.remindAt}
                                   onChange={e => setSchedule(s => ({ ...s, remindAt: e.target.value }))}
                                   slotProps={{ inputLabel: { shrink: true } }} />
                    </>
                )}
                {status === 'scheduled'
                    ? <Button variant="contained" onClick={saveScheduled} disabled={busy}>Save changes</Button>
                    : <Button variant="contained" endIcon={<SendIcon />} disabled={busy || !ready}
                              onClick={() => setDialog('confirm')} data-testid="composer-review">Review and send</Button>}
            </Paper>

            <AudienceDialog open={dialog === 'audience'} onClose={() => setDialog(null)}
                            recipients={audience.data?.recipients || []}
                            subject={preview.data?.email.subject.replace(/^\[WhaP\] /, '')} />
            <ConfirmDialog open={dialog === 'confirm'} onClose={() => setDialog(null)} onConfirm={scheduleIt} busy={busy}
                           subject={(preview.data?.email.subject || form.subject).replace(/^\[WhaP\] /, '')}
                           audience={audience.data} when={when} />
            <Dialog open={dialog === 'discard' || dialog === 'cancel'} onClose={() => setDialog(null)}>
                <DialogTitle>{dialog === 'cancel' ? 'Cancel this notification?' : 'Delete this draft?'}</DialogTitle>
                <DialogContent>
                    <DialogContentText>{dialog === 'cancel'
                        ? 'Nobody gets it. It stays in the list as cancelled, where you can copy or delete it.'
                        : 'The draft is deleted.'}</DialogContentText>
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setDialog(null)}>Keep it</Button>
                    <Button color="error" onClick={dialog === 'cancel' ? cancelScheduled : discard} disabled={busy}>
                        {dialog === 'cancel' ? 'Cancel notification' : 'Delete draft'}</Button>
                </DialogActions>
            </Dialog>
        </>
    );
}

export default NotificationComposer;
