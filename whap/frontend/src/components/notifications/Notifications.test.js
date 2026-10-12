import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import api from '../../services/api';
import NotificationComposer, { scheduleTimes } from './NotificationComposer';
import NotificationList from './NotificationList';
import NotificationReport from './NotificationReport';
import { formatTime, shiftLocal, toLocalInput } from './shared';

jest.mock('../../services/api', () => ({
    __esModule: true,
    default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
}));

afterEach(() => jest.clearAllMocks());

const OPTIONS = {
    servers: [{ id: 1, hostname: 'tycho', containers: 2 }],
    images: [{ name: 'worker_local_ubuntu2404_ssh', containers: 1 }],
    datasets: [{ name: 'coco', containers: 1 }],
    groups: [{ id: 3, name: 'students', members: 1 }],
    templates: {
        maintenance: { subject: '{server} restarts on {start}', body: 'Hello {name},\n\nmaintenance' },
        image: { subject: 'A new version of {image}', body: 'Hello {name},\n\nimage' },
        dataset: { subject: 'New data in {dataset}', body: 'Hello {name},\n\ndataset' },
        group: { subject: '', body: 'Hello {name},\n\n' },
        announcement: { subject: '', body: 'Hello {name},\n\n' },
    },
    fields: { maintenance: ['name', 'server', 'start'], image: ['name', 'image'], dataset: ['name'],
              group: ['name', 'group'], announcement: ['name'] },
    impacts: {}, timezone: 'Europe/Berlin', channels: { email: true, matrix: true },
};

const DRAFT = {
    id: 7, kind: 'maintenance', status: 'draft', subject: 'tycho restarts on {start}', body: 'Hello {name}',
    params: { server_ids: [1], start: '2030-10-20T06:00:00+00:00', end: '2030-10-20T07:00:00+00:00', impact: 'stopped' },
    updated_at: '2030-10-12T08:42:00Z', editable: true,
};

const AUDIENCE = {
    summary: { total: 2, reached: 1, email: 1, matrix: 0, unreachable: { topic_off: 0, all_off: 0, no_address: 1 } },
    recipients: [
        { user_uid: 'ldap:alice', username: 'alice', name: 'Alice', unreachable: null,
          channels: [{ channel: 'email', address: 'alice@uni.example' }],
          containers: [{ id: 1, project: 'thesis', image: 'worker_local_ubuntu2404_ssh', server: 'tycho' }] },
        { user_uid: 'ldap:bob', username: 'bob', name: 'Bob', unreachable: 'no_address', channels: [], containers: [] },
    ],
};

const PREVIEW = {
    recipients: [{ user_uid: 'ldap:alice', username: 'alice' }, { user_uid: 'ldap:bob', username: 'bob' }],
    user_uid: 'ldap:alice', username: 'alice',
    email: { subject: '[WhaP] tycho restarts on Sun 20 Oct, 08:00', text: 'Hello Alice', html: '<p>Hello Alice</p>',
             to: 'alice@uni.example' },
    matrix: { text: 'x', html: '<p><strong>tycho restarts</strong></p><p>Hello Alice</p>' },
};

function backend({ audience = AUDIENCE, draft = DRAFT } = {}) {
    api.get.mockImplementation(url => Promise.resolve({ data: url.endsWith('/7') ? draft : [] }));
    api.put.mockImplementation((url, body) => Promise.resolve({ data: { ...draft, ...body } }));
    api.post.mockImplementation((url, body) => {
        if (url.endsWith('/audience')) {
            return audience instanceof Error ? Promise.reject(audience) : Promise.resolve({ data: audience });
        }
        if (url.endsWith('/preview')) {
            const who = body.user_uid === 'ldap:bob' ? { user_uid: 'ldap:bob', username: 'bob' } : {};
            return Promise.resolve({ data: { ...PREVIEW, ...who } });
        }
        if (url.endsWith('/schedule')) return Promise.resolve({ data: { ...draft, status: 'scheduled', send_at: body.send_at } });
        if (url.endsWith('/test')) return Promise.resolve({ data: { as_user: 'alice', results: [{ channel: 'email', ok: true, address: 'admin@uni.example' }] } });
        if (url.endsWith('/cancel')) return Promise.resolve({ data: { ...draft, status: 'cancelled' } });
        return Promise.resolve({ data: { ...draft, ...body, id: 8 } });
    });
}

// --- time helpers ---------------------------------------------------------------

test('times are shown and edited in the server\'s zone', () => {
    expect(formatTime('2030-10-20T06:00:00Z', 'Europe/Berlin')).toBe('Sun 20 Oct, 08:00');
    expect(toLocalInput('2030-10-20T06:00:00+00:00', 'Europe/Berlin')).toBe('2030-10-20T08:00');
    expect(toLocalInput('2030-10-20T08:00', 'Europe/Berlin')).toBe('2030-10-20T08:00');
    expect(shiftLocal('2030-10-20T08:00', -24)).toBe('2030-10-19T08:00');
});

test('"1 day before" sends a day ahead and reminds an hour ahead', () => {
    const params = { start: '2030-10-20T08:00' };
    expect(scheduleTimes({ mode: 'day_before' }, 'maintenance', params))
        .toEqual({ send_at: '2030-10-19T08:00', remind_at: '2030-10-20T07:00' });
    expect(scheduleTimes({ mode: 'now' }, 'maintenance', params)).toEqual({ send_at: null, remind_at: null });
    expect(scheduleTimes({ mode: 'at', sendAt: '2030-10-18T09:00', remindAt: '' }, 'image', {}))
        .toEqual({ send_at: '2030-10-18T09:00', remind_at: null });
});

// --- composer --------------------------------------------------------------------

async function openDraft(props = {}) {
    render(<NotificationComposer id={7} options={OPTIONS} onBack={jest.fn()} onDone={jest.fn()} {...props} />);
    await screen.findByText('1. What is it about?');
}

test('the composer shows who gets it and what they read', async () => {
    backend();
    await openDraft();
    expect(screen.getByTestId('composer-start')).toHaveValue('2030-10-20T08:00');
    expect(await screen.findByTestId('audience-count')).toHaveTextContent('1');
    expect(screen.getByTestId('audience-card')).toHaveTextContent("1 won't be notified");
    expect(await screen.findByTestId('preview-email')).toHaveTextContent('Hello Alice');
    const audienceCalls = api.post.mock.calls.filter(([url]) => url.endsWith('/audience'));
    expect(audienceCalls).toEqual([['/api/admin/notifications/audience', {
        kind: 'maintenance', params: { server_ids: [1], start: '2030-10-20T08:00', end: '2030-10-20T09:00',
                                       impact: 'stopped' } }]]);
});

test('the preview steps through the recipients', async () => {
    backend();
    await openDraft();
    await screen.findByText('alice · 1 of 2');
    fireEvent.click(screen.getByLabelText('Next recipient'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/admin/notifications/preview',
        expect.objectContaining({ user_uid: 'ldap:bob' })));
    expect(await screen.findByText('bob · 2 of 2')).toBeInTheDocument();
});

test('the recipient list names those who will not be reached', async () => {
    backend();
    await openDraft();
    fireEvent.click(await screen.findByTestId('audience-show-all'));
    const dialog = screen.getByTestId('audience-dialog');
    expect(within(dialog).getByText('No email or Matrix')).toBeInTheDocument();
    fireEvent.click(within(dialog).getByLabelText("Only users who won't be notified"));
    expect(within(dialog).queryByText('alice')).not.toBeInTheDocument();
});

test('switching the type replaces an untouched template but keeps what was written', async () => {
    backend();
    render(<NotificationComposer id={null} options={OPTIONS} onBack={jest.fn()} onDone={jest.fn()} />);
    expect(screen.getByTestId('composer-body')).toHaveValue('Hello {name},\n\nmaintenance');
    fireEvent.click(screen.getByTestId('composer-kind-image'));
    expect(screen.getByTestId('composer-body')).toHaveValue('Hello {name},\n\nimage');
    expect(screen.getByTestId('composer-subject')).toHaveValue('A new version of {image}');
    fireEvent.change(screen.getByTestId('composer-body'), { target: { value: 'My own words' } });
    fireEvent.click(screen.getByTestId('composer-kind-group'));
    expect(screen.getByTestId('composer-body')).toHaveValue('My own words');
});

test('an insert chip puts the field into the message', async () => {
    backend();
    render(<NotificationComposer id={null} options={OPTIONS} onBack={jest.fn()} onDone={jest.fn()} />);
    const body = screen.getByTestId('composer-body');
    fireEvent.change(body, { target: { value: 'Hi ' } });
    body.setSelectionRange(3, 3);
    fireEvent.click(screen.getByText('{server}'));
    expect(body).toHaveValue('Hi {server}');
});

test('a new draft saves itself once something is written', async () => {
    backend();
    render(<NotificationComposer id={null} options={OPTIONS} onBack={jest.fn()} onDone={jest.fn()} />);
    await new Promise(r => setTimeout(r, 1500));
    expect(api.post).not.toHaveBeenCalledWith('/api/admin/notifications', expect.anything());
    fireEvent.change(screen.getByTestId('composer-subject'), { target: { value: 'Planned downtime' } });
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/admin/notifications',
        expect.objectContaining({ subject: 'Planned downtime', kind: 'maintenance' })), { timeout: 3000 });
    expect(await screen.findByTestId('composer-saved')).toHaveTextContent('Draft saved');
});

test('review and send confirms once, then schedules a day ahead with a reminder', async () => {
    backend();
    const onDone = jest.fn();
    await openDraft({ onDone });
    await screen.findByTestId('audience-count');
    await waitFor(() => expect(screen.getByTestId('composer-review')).toBeEnabled());
    fireEvent.click(screen.getByTestId('composer-review'));

    const dialog = screen.getByTestId('confirm-dialog');
    expect(dialog).toHaveTextContent('Schedule “tycho restarts on Sun 20 Oct, 08:00” for 1 user?');
    expect(dialog).toHaveTextContent('Sat 19 Oct, 08:00');
    expect(dialog).toHaveTextContent("1 user won't hear about it: bob (no email or matrix)");
    fireEvent.click(within(dialog).getByTestId('confirm-send'));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(api.post).toHaveBeenCalledWith('/api/admin/notifications/7/schedule',
        { send_at: '2030-10-19T08:00', remind_at: '2030-10-20T07:00' });
    expect(onDone.mock.calls[0][0]).toMatch(/^Scheduled “/);
});

test('nothing can be sent while it reaches nobody or is incomplete', async () => {
    backend({ audience: Object.assign(new Error('400'),
                                      { response: { data: { message: 'Choose at least one server.' } } }) });
    await openDraft();
    expect(await screen.findByTestId('audience-hint')).toHaveTextContent('Choose at least one server.');
    expect(screen.getByTestId('composer-review')).toBeDisabled();
});

test('the test goes to the admin and says as whom it was written', async () => {
    backend();
    await openDraft();
    fireEvent.click(screen.getByTestId('composer-test'));
    expect(await screen.findByTestId('composer-test-result'))
        .toHaveTextContent('Test written as for alice: sent to admin@uni.example.');
});

test('a scheduled notification is saved explicitly and can be cancelled', async () => {
    backend({ draft: { ...DRAFT, status: 'scheduled', send_at: '2030-10-19T06:00:00Z' } });
    const onDone = jest.fn();
    await openDraft({ onDone });
    expect(screen.getByTestId('composer-saved')).toHaveTextContent('Scheduled for Sat 19 Oct, 08:00');
    expect(screen.getByTestId('composer-kind-image')).toBeDisabled();
    fireEvent.click(screen.getByText('Cancel notification'));
    fireEvent.click(within(screen.getByRole('dialog')).getByText('Cancel notification'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/admin/notifications/7/cancel'));
    expect(onDone.mock.calls[0][0]).toMatch(/Nobody gets it/);
});

// --- list and report ----------------------------------------------------------------

test('the list shows each notification\'s state and opens it', () => {
    const onOpen = jest.fn();
    const sent = { ...DRAFT, id: 1, status: 'sent', title: 'Sent one', about: 'tycho', recipients: 9,
                   sent_at: '2030-10-12T08:14:00Z', deliveries: { sent: 12, pending: 0, failed: 1 }, editable: false };
    const draft = { ...DRAFT, id: 2, title: 'tycho restarts on Sun 20 Oct, 08:00', about: 'tycho',
                    deliveries: { sent: 0, pending: 0, failed: 0 } };
    render(<NotificationList notifications={[sent, draft]} timeZone="Europe/Berlin" onNew={jest.fn()}
                             onOpen={onOpen} onFollowUp={jest.fn()} />);
    const [first, second] = screen.getAllByTestId('notif-row');
    expect(first).toHaveTextContent('12 delivered');
    expect(first).toHaveTextContent('1 failed');
    expect(first).toHaveTextContent('Sent Sat 12 Oct, 10:14');
    expect(first).toHaveTextContent('Sent one');
    expect(second).toHaveTextContent('tycho restarts on Sun 20 Oct, 08:00');
    expect(second).toHaveTextContent('Draft');
    fireEvent.click(second);
    expect(onOpen).toHaveBeenCalledWith(draft);
});

test('the report lists deliveries and retries the failed ones', async () => {
    const notification = { ...DRAFT, status: 'sent', about: 'tycho', sent_at: '2030-10-12T08:14:00Z',
                           deliveries: { sent: 1, pending: 0, failed: 1 }, editable: false };
    api.get.mockImplementation(url => Promise.resolve({ data: url.endsWith('/deliveries') ? [
        { id: 1, username: 'alice', channel: 'email', address: 'alice@uni.example', status: 'sent',
          attempts: 1, sent_at: '2030-10-12T08:14:00Z', phase: 'notice' },
        { id: 2, username: 'bob', channel: 'email', address: 'bob@uni.example', status: 'failed', attempts: 3,
          last_error: '550 5.1.1 mailbox unavailable', phase: 'notice' },
    ] : notification }));
    api.post.mockResolvedValue({ data: { retrying: 1 } });
    render(<NotificationReport id={7} timeZone="Europe/Berlin" onBack={jest.fn()} onOpenDraft={jest.fn()} />);
    const rows = await screen.findAllByTestId('report-delivery');
    expect(rows[1]).toHaveTextContent('Failed after 3 tries');
    expect(rows[1]).toHaveTextContent('550 5.1.1 mailbox unavailable');
    fireEvent.click(screen.getByTestId('report-retry'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/admin/notifications/7/retry'));
});
