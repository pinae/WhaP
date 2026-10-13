import React, { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Alert, Box, CircularProgress, Snackbar } from '@mui/material';
import api from '../services/api';
import { API } from './notifications/shared';
import NotificationList from './notifications/NotificationList';
import NotificationComposer from './notifications/NotificationComposer';
import NotificationReport from './notifications/NotificationReport';
import ExpiryOverview from './notifications/ExpiryOverview';

/**
 * The Admin panel's Notifications tab. ?n=new composes; ?n=<id> opens a
 * notification: the composer while it can still be edited, else its report.
 */
function AdminNotifications() {
    const [searchParams, setSearchParams] = useSearchParams();
    const open = searchParams.get('n');
    const [options, setOptions] = useState(null);
    const [notifications, setNotifications] = useState(null);
    const [opened, setOpened] = useState(null);  // the notification ?n=<id> names
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
    useEffect(() => {
        setOpened(null);
        if (!open || open === 'new') return;
        api.get(`${API}/${open}`).then(r => setOpened(r.data))
            .catch(err => setError(err.response?.data?.message || 'Could not load the notification.'));
    }, [open]);

    const go = (n) => setSearchParams(n ? { tab: 'notifications', n: String(n) } : { tab: 'notifications' });
    const done = (text) => { setMessage(text); go(null); };

    if (error) return <Alert severity="error" onClose={() => { setError(''); go(null); }}>{error}</Alert>;
    const waiting = <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}><CircularProgress /></Box>;
    if (!options) return waiting;

    let view;
    if (!open) {
        view = (
            <>
                <NotificationList notifications={notifications || []} loading={!notifications}
                                  timeZone={options.timezone} onNew={() => go('new')} onOpen={n => go(n.id)}
                                  onFollowUp={n => api.post(`${API}/${n.id}/copy`, { follow_up: true })
                                      .then(r => go(r.data.id))} />
                <ExpiryOverview timeZone={options.timezone} onOpen={n => go(n.id)} />
            </>
        );
    } else if (open === 'new') {
        view = <NotificationComposer key="new" id={null} options={options} onBack={() => go(null)} onDone={done} />;
    } else if (!opened || String(opened.id) !== open) {
        view = waiting;
    } else if (opened.editable) {
        view = <NotificationComposer key={open} id={opened.id} options={options} onBack={() => go(null)} onDone={done} />;
    } else {
        view = <NotificationReport id={opened.id} timeZone={options.timezone} onBack={() => go(null)}
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
