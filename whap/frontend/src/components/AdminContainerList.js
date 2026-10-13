import React, { memo, useCallback, useDeferredValue, useMemo, useRef, useState } from 'react';
import {
    Button, CircularProgress, FormControl, IconButton, InputLabel, MenuItem, Paper, Select, Stack, Table,
    TableBody, TableCell, TableContainer, TableHead, TableRow, TableSortLabel, TextField, Typography,
} from '@mui/material';
import StopCircleIcon from '@mui/icons-material/StopCircle';
import DeleteForeverIcon from '@mui/icons-material/DeleteForever';
import EditIcon from '@mui/icons-material/Edit';
import AddIcon from '@mui/icons-material/Add';

export const stringToColor = (string) => {
    let hash = 0;
    for (let i = 0; i < string.length; i++) {
        hash = string.charCodeAt(i) + ((hash << 5) - hash);
    }
    let color = '#';
    for (let i = 0; i < 3; i++) {
        const value = (hash >> (i * 8)) & 0xFF;
        color += `00${value.toString(16)}`.slice(-2);
    }
    return color;
};

// "10.0.0.12" sorts after "10.0.0.9": compare the numbers, not the text.
const ipKey = (ip) => (ip ? ip.split('.').map(part => part.padStart(3, '0')).join('.') : '');

const COLUMNS = [
    { key: 'id', label: 'ID / Name', value: r => r.id },
    { key: 'user', label: 'User', value: r => (r.user_display || '').toLowerCase() },
    { key: 'project', label: 'Project', value: r => (r.project || '').toLowerCase() },
    { key: 'image', label: 'Image', value: r => r.image || '' },
    { key: 'server', label: 'Server', value: r => r.server || '' },
    { key: 'ip', label: 'IP', value: r => ipKey(r.ip_address) },
    { key: 'status', label: 'Status', value: r => r.status || '' },
    { key: 'created', label: 'Created', value: r => r.created_at || '' },
];

const EMPTY_FILTERS = { user: '', ip: '', server: '', image: '' };

export function filterContainers(containers, filters) {
    const user = filters.user.trim().toLowerCase();
    const ip = filters.ip.trim();
    return containers.filter(r =>
        (!user || `${r.user_display} ${r.username}`.toLowerCase().includes(user))
        && (!ip || (r.ip_address || '').includes(ip))
        && (!filters.server || r.server === filters.server)
        && (!filters.image || r.image === filters.image));
}

export function sortContainers(containers, by, direction) {
    const column = COLUMNS.find(c => c.key === by) || COLUMNS[0];
    const sign = direction === 'asc' ? 1 : -1;
    return [...containers].sort((a, b) => {
        const x = column.value(a);
        const y = column.value(b);
        return (x < y ? -1 : x > y ? 1 : a.id - b.id) * sign;
    });
}

const countBy = (rows, key) => {
    const counts = new Map();
    rows.forEach(r => r[key] && counts.set(r[key], (counts.get(r[key]) || 0) + 1));
    return [...counts.entries()].sort(([a], [b]) => a.localeCompare(b));
};

const formatCreated = (iso) => (iso ? new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '');

const statusColor = (status) => (status === 'RUNNING' ? 'success' : status === 'STOPPED' ? 'default'
    : status === 'ERROR' ? 'error' : 'warning');

// The rows use these classes instead of their own sx props and Chips: MUI resolves
// every sx object and Chip anew for each row, which was most of the table's render time.
const tableStyles = {
    '& .cl-id': { fontWeight: 'bold', display: 'block' },
    '& .cl-name': { display: 'block', fontFamily: 'monospace', fontSize: '0.75rem', color: 'text.secondary',
                    wordBreak: 'break-all' },
    '& .cl-mono': { fontFamily: 'monospace', fontSize: '0.8rem' },
    '& .cl-created': { whiteSpace: 'nowrap', color: 'text.secondary', fontSize: '0.8rem' },
    '& .cl-actions': { display: 'flex', justifyContent: 'flex-end' },
    '& .cl-chip': { display: 'inline-block', px: 1, borderRadius: 2.5, lineHeight: '20px', fontSize: '0.7rem',
                    fontWeight: 500, whiteSpace: 'nowrap', border: '1px solid', borderColor: 'divider' },
    '& .cl-status': { lineHeight: '22px', fontSize: '0.8125rem', fontWeight: 400, px: 1.25 },
    '& .cl-status-success': { bgcolor: 'success.main', borderColor: 'success.main', color: 'success.contrastText' },
    '& .cl-status-error': { color: 'error.main', borderColor: 'error.main' },
    '& .cl-status-warning': { color: 'warning.main', borderColor: 'warning.main' },
};

/** One row; re-rendered only when its container or stopping state changes. */
const ContainerRow = memo(function ContainerRow({ row, isStopping, onEdit, onStop, onDelete }) {
    const canStop = ['RUNNING', 'PAUSED', 'STARTING', 'ERROR'].includes(row.status);
    const serverColor = stringToColor(row.server || 'unknown');
    return (
        <TableRow hover data-testid="admin-container-row" data-container-id={row.id}>
            <TableCell>
                <span className="cl-id">#{row.id}</span>
                <span className="cl-name">{row.container_name || '-'}</span>
            </TableCell>
            <TableCell>{row.user_display}</TableCell>
            <TableCell>{row.project}</TableCell>
            <TableCell><span className="cl-mono">{row.image}</span></TableCell>
            <TableCell>
                <span className="cl-chip" style={{ backgroundColor: `${serverColor}20`, borderColor: serverColor }}>
                    {row.server}
                </span>
            </TableCell>
            <TableCell className="cl-mono">{row.ip_address || '—'}</TableCell>
            <TableCell>
                <span className={`cl-chip cl-status cl-status-${statusColor(row.status)}`}>{row.status}</span>
            </TableCell>
            <TableCell className="cl-created">{formatCreated(row.created_at)}</TableCell>
            <TableCell align="right">
                {/* Native titles: an MUI Tooltip per button doubled the time the table took to render. */}
                <div className="cl-actions">
                    <IconButton title="Manually Edit Record" aria-label="Manually Edit Record" size="small"
                                color="primary" onClick={() => onEdit(row)}>
                        <EditIcon fontSize="small" />
                    </IconButton>
                    <span title="Stop Container (via Ansible)">
                        <IconButton aria-label="Stop Container (via Ansible)" size="small" color="warning"
                                    onClick={() => onStop(row.id)} disabled={!canStop || isStopping}>
                            {isStopping ? <CircularProgress size={18} /> : <StopCircleIcon fontSize="small" />}
                        </IconButton>
                    </span>
                    <IconButton title="Delete DB Record Only" aria-label="Delete DB Record Only" size="small"
                                color="error" onClick={() => onDelete(row)}>
                        <DeleteForeverIcon fontSize="small" />
                    </IconButton>
                </div>
            </TableCell>
        </TableRow>
    );
});

function AdminContainerList({ containers, onStop, onDelete, onAddContainer, onEditContainer, stoppingContainerId }) {
    const [filters, setFilters] = useState(EMPTY_FILTERS);
    const [sort, setSort] = useState({ by: 'created', direction: 'desc' });
    // Typing stays responsive; the table catches up.
    const deferredFilters = useDeferredValue(filters);

    // The page passes new handler functions on every render; the rows get stable ones.
    const handlers = useRef({});
    handlers.current = { onStop, onDelete, onEditContainer };
    const onEdit = useCallback(row => handlers.current.onEditContainer(row), []);
    const onStopRow = useCallback(id => handlers.current.onStop(id), []);
    const onDeleteRow = useCallback(row => handlers.current.onDelete(row), []);

    const all = useMemo(() => containers || [], [containers]);
    const servers = useMemo(() => countBy(all, 'server'), [all]);
    const images = useMemo(() => countBy(all, 'image'), [all]);
    const shown = useMemo(() => sortContainers(filterContainers(all, deferredFilters), sort.by, sort.direction),
        [all, deferredFilters, sort]);

    const setFilter = (key) => (e) => setFilters(f => ({ ...f, [key]: e.target.value }));
    const sortBy = (key) => setSort(s => ({ by: key, direction: s.by === key && s.direction === 'asc' ? 'desc' : 'asc' }));
    const filtering = Object.values(filters).some(Boolean);

    return (
        <>
            <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}
                   data-testid="admin-container-filters">
                <TextField size="small" label="User" value={filters.user} onChange={setFilter('user')} sx={{ width: 200 }}
                           slotProps={{ htmlInput: { 'data-testid': 'filter-user' } }} />
                <TextField size="small" label="IP" value={filters.ip} onChange={setFilter('ip')} sx={{ width: 160 }}
                           slotProps={{ htmlInput: { 'data-testid': 'filter-ip' } }} />
                <FormControl size="small" sx={{ minWidth: 160 }}>
                    <InputLabel id="filter-server-label">Server</InputLabel>
                    <Select labelId="filter-server-label" label="Server" value={filters.server}
                            onChange={setFilter('server')} data-testid="filter-server">
                        <MenuItem value=""><em>All</em></MenuItem>
                        {servers.map(([name, n]) => <MenuItem key={name} value={name}>{name} ({n})</MenuItem>)}
                    </Select>
                </FormControl>
                <FormControl size="small" sx={{ minWidth: 260 }}>
                    <InputLabel id="filter-image-label">Image</InputLabel>
                    <Select labelId="filter-image-label" label="Image" value={filters.image}
                            onChange={setFilter('image')} data-testid="filter-image">
                        <MenuItem value=""><em>All</em></MenuItem>
                        {images.map(([name, n]) => <MenuItem key={name} value={name}>{name} ({n})</MenuItem>)}
                    </Select>
                </FormControl>
                {filtering && <Button size="small" onClick={() => setFilters(EMPTY_FILTERS)}>Clear filters</Button>}
                <Typography variant="body2" color="text.secondary" sx={{ flexGrow: 1 }} data-testid="admin-container-count">
                    {filtering ? `Showing ${shown.length} of ${all.length}` : `${all.length} containers`}
                </Typography>
                <Button variant="contained" startIcon={<AddIcon />} onClick={onAddContainer} size="small">
                    Manually Add Container
                </Button>
            </Stack>
            <TableContainer component={Paper} sx={tableStyles}>
                <Table size="small" aria-label="all containers table">
                    <TableHead>
                        <TableRow>
                            {COLUMNS.map(c => (
                                <TableCell key={c.key} sx={{ fontWeight: 'bold' }}
                                           sortDirection={sort.by === c.key ? sort.direction : false}>
                                    <TableSortLabel active={sort.by === c.key}
                                                    direction={sort.by === c.key ? sort.direction : 'asc'}
                                                    onClick={() => sortBy(c.key)} data-testid={`sort-${c.key}`}>
                                        {c.label}
                                    </TableSortLabel>
                                </TableCell>
                            ))}
                            <TableCell align="right" sx={{ fontWeight: 'bold' }}>Actions</TableCell>
                        </TableRow>
                    </TableHead>
                    <TableBody>
                        {shown.map(row => (
                            <ContainerRow key={row.id} row={row} isStopping={stoppingContainerId === row.id}
                                          onEdit={onEdit} onStop={onStopRow} onDelete={onDeleteRow} />
                        ))}
                        {shown.length === 0 && (
                            <TableRow>
                                <TableCell colSpan={COLUMNS.length + 1}
                                           sx={{ textAlign: 'center', py: 3, color: 'text.secondary' }}>
                                    {all.length ? 'No container matches these filters.' : 'No containers found.'}
                                </TableCell>
                            </TableRow>
                        )}
                    </TableBody>
                </Table>
            </TableContainer>
        </>
    );
}

export default AdminContainerList;
