import React, { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Alert, Box, CircularProgress, Snackbar } from '@mui/material';
import api from '../services/api';
import { API } from './notifications/shared';
import NotificationList from './notifications/NotificationList';
import NotificationComposer from './notifications/NotificationComposer';
import NotificationReport from './notifications/NotificationReport';

/**
 * The Admin panel's Notifications tab. ?n=new composes; ?n=<id> opens a
 * notification: the composer while it can still be edited, else its report.
 */
function AdminNotifications() {
    const [searchParams, setSearchParams] = useSearchParams();
    const open = searchParams.get('n');
    const [options, setOptions] = useState(null);
    const [notifications, setNotifications] = useState(null);
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');

    const load = useCallback(() => {
        api.get(API).then(r => setNotifications(r.data))
            .catch(err => setError(err.response?.data?.message || 'Could not load the notifications.'));
    }, []);

    useEffect(() => {
        api.get(`${API}/options`).then(r => setOptions(r.data))
            .catch(err => setError(err.response?.data?.message || 'Could not load the composer.'));
    }, []);
    useEffect(() => { if (!open) load(); }, [open, load]);

    const go = (n) => setSearchParams(n ? { tab: 'notifications', n: String(n) } : { tab: 'notifications' });
    const done = (text) => { setMessage(text); go(null); };

    if (error) return <Alert severity="error">{error}</Alert>;
    if (!options) return <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}><CircularProgress /></Box>;

    const existing = open && open !== 'new' && notifications?.find(n => String(n.id) === open);
    let view;
    if (!open) {
        view = <NotificationList notifications={notifications || []} loading={!notifications} timeZone={options.timezone}
                                 onNew={() => go('new')} onOpen={n => go(n.id)}
                                 onFollowUp={n => api.post(`${API}/${n.id}/copy`, { follow_up: true })
                                     .then(r => go(r.data.id))} />;
    } else if (open === 'new' || (existing ? existing.editable : true)) {
        // An id not in the list yet (a fresh copy) opens in the composer, which loads it.
        view = <NotificationComposer key={open} id={open === 'new' ? null : Number(open)} options={options}
                                     onBack={() => go(null)} onDone={done} />;
    } else {
        view = <NotificationReport id={Number(open)} timeZone={options.timezone} onBack={() => go(null)}
                                   onOpenDraft={newId => go(newId)} />;
    }
    return (
        <>
            {view}
            <Snackbar open={Boolean(message)} autoHideDuration={6000} onClose={() => setMessage('')}
                      message={message} data-testid="notif-message" />
        </>
    );
}

export default AdminNotifications;
