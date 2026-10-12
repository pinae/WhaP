import React from 'react';
import { Chip } from '@mui/material';
import ComputerIcon from '@mui/icons-material/Computer';
import LayersIcon from '@mui/icons-material/Layers';
import StorageIcon from '@mui/icons-material/Storage';
import CampaignIcon from '@mui/icons-material/Campaign';
import GroupsIcon from '@mui/icons-material/Groups';
import HourglassBottomIcon from '@mui/icons-material/HourglassBottom';

export const API = '/api/admin/notifications';

export const KINDS = {
    maintenance: { label: 'Maintenance', icon: <ComputerIcon fontSize="small" />, color: 'warning' },
    image: { label: 'Image update', icon: <LayersIcon fontSize="small" />, color: 'info' },
    dataset: { label: 'Dataset update', icon: <StorageIcon fontSize="small" />, color: 'secondary' },
    group: { label: 'Group', icon: <GroupsIcon fontSize="small" />, color: 'primary' },
    announcement: { label: 'Everyone', icon: <CampaignIcon fontSize="small" />, color: undefined },
    expiry: { label: 'Expiry reminder', icon: <HourglassBottomIcon fontSize="small" />, color: undefined },
};

export const COMPOSABLE = ['maintenance', 'image', 'dataset', 'group', 'announcement'];

export const UNREACHABLE = {
    topic_off: 'Turned this topic off',
    all_off: 'All notifications off',
    no_address: 'No email or Matrix',
};

export function KindChip({ kind }) {
    const k = KINDS[kind] || { label: kind };
    return <Chip size="small" variant="outlined" icon={k.icon} label={k.label} color={k.color} />;
}

/** 'Mon 19 Oct, 08:00' in the server's time zone, from an ISO time. */
export function formatTime(iso, timeZone) {
    if (!iso) return '';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
        timeZone: timeZone || 'UTC', weekday: 'short', day: 'numeric', month: 'short',
        hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }).formatToParts(date).map(p => [p.type, p.value]));
    return `${parts.weekday} ${parts.day} ${parts.month}, ${parts.hour}:${parts.minute}`;
}

/** A value for <input type="datetime-local"> showing ``iso`` in ``timeZone``. Naive values pass through. */
export function toLocalInput(iso, timeZone) {
    if (!iso) return '';
    if (!/[zZ]|[+-]\d\d:\d\d$/.test(iso)) return iso.slice(0, 16);
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
        timeZone: timeZone || 'UTC', year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }).formatToParts(new Date(iso)).map(p => [p.type, p.value]));
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

/** A local 'YYYY-MM-DDTHH:mm' moved by ``hours``, still local (the server reads it in its zone). */
export function shiftLocal(local, hours) {
    if (!local) return '';
    const moved = new Date(new Date(`${local}:00Z`).getTime() + hours * 3600 * 1000);
    return moved.toISOString().slice(0, 16);
}

export function names(list, max = 3) {
    if (list.length <= max) return list.join(', ');
    return `${list.slice(0, max).join(', ')} and ${list.length - max} more`;
}
