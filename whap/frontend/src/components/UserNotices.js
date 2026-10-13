import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
    Alert, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, Stack,
} from '@mui/material';
import ComputerIcon from '@mui/icons-material/Computer';
import HourglassBottomIcon from '@mui/icons-material/HourglassBottom';
import api from '../services/api';

/**
 * Maintenance on the user's servers and their local projects about to expire,
 * above the User Panel. A link ?prolong=<container id> (from an expiry
 * reminder) asks to prolong that container.
 */
function UserNotices({ containers, onProlonged }) {
    const [searchParams, setSearchParams] = useSearchParams();
    const [notices, setNotices] = useState([]);
    const [asked, setAsked] = useState(null);  // the container to prolong, from a link or a button
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState(null);  // {severity, text}

    const load = useCallback(() => {
        api.get('/api/notices').then(r => setNotices(r.data)).catch(() => {});
    }, []);
    useEffect(() => { load(); }, [load]);

    const linked = searchParams.get('prolong');
    // A link is acted on once: the container list reloads after prolonging,
    // possibly before the URL has dropped ?prolong=.
    const handled = useRef(null);
    useEffect(() => {
        if (!linked || !containers || handled.current === linked) return;
        handled.current = linked;
        const container = containers.find(c => String(c.id) === linked);
        if (container) {
            setAsked({ id: container.id, project: container.project, server: container.server });
        } else if (containers.length) {
            setResult({ severity: 'warning', text: 'That container is not one of yours, or it no longer exists.' });
        }
    }, [linked, containers]);

    const forget = () => {
        setAsked(null);
        if (linked) {
            const rest = new URLSearchParams(searchParams);
            rest.delete('prolong');
            setSearchParams(rest);
        }
    };

    const prolong = async () => {
        setBusy(true);
        try {
            await api.post(`/api/containers/${asked.id}/prolong`);
            setResult({ severity: 'success', text: `“${asked.project}” now expires four weeks later.` });
            load();
            if (onProlonged) onProlonged();
        } catch (err) {
            setResult({ severity: 'error', text: err.response?.data?.message || 'Prolonging failed.' });
        } finally {
            setBusy(false);
            forget();
        }
    };

    return (
        <>
            {(notices.length > 0 || result) && (
                <Stack spacing={1} sx={{ mb: 3 }} data-testid="user-notices">
                    {result && <Alert severity={result.severity} onClose={() => setResult(null)}
                                      data-testid="notice-result">{result.text}</Alert>}
                    {notices.map(n => n.kind === 'maintenance' ? (
                        <Alert key={`m${n.id}`} severity="warning" icon={<ComputerIcon />} data-testid="notice-maintenance">
                            <b>{n.title}.</b> What happens: {n.impact} Your containers there: {n.containers.join(', ')}.
                        </Alert>
                    ) : (
                        <Alert key={`e${n.container_id}`} severity={n.urgent ? 'error' : 'warning'}
                               icon={<HourglassBottomIcon />} data-testid="notice-expiry"
                               action={<Button color="inherit" size="small" variant="outlined" sx={{ whiteSpace: 'nowrap' }}
                                               onClick={() => setAsked({ id: n.container_id, project: n.project,
                                                                         server: n.server })}>
                                   Prolong 4 weeks</Button>}>
                            <b>“{n.project}” on {n.server} expires {n.expires_in}</b> ({n.ttl_date}). Its directory
                            there is deleted then, except <code>~/synced</code>.
                        </Alert>
                    ))}
                </Stack>
            )}
            <Dialog open={Boolean(asked)} onClose={forget} data-testid="prolong-dialog">
                <DialogTitle>Prolong “{asked?.project}” by four weeks?</DialogTitle>
                <DialogContent>
                    <DialogContentText>
                        Its local project directory on {asked?.server} is then kept four weeks longer.
                    </DialogContentText>
                </DialogContent>
                <DialogActions>
                    <Button onClick={forget} disabled={busy}>Not now</Button>
                    <Button variant="contained" onClick={prolong} disabled={busy} data-testid="prolong-confirm">
                        {busy ? <CircularProgress size={20} /> : 'Prolong'}</Button>
                </DialogActions>
            </Dialog>
        </>
    );
}

export default UserNotices;
