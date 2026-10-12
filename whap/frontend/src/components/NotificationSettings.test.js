import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import api from '../services/api';
import NotificationSettings, { daysBefore } from './NotificationSettings';

jest.mock('../services/api', () => ({
    __esModule: true,
    default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
}));

afterEach(() => jest.clearAllMocks());

const view = (changes = {}) => ({
    email: { enabled: true, address: 'alice@uni.example', available: true },
    matrix: { available: true, enabled: false, id: null, pending_id: null, suggestion: '@alice:matrix.uni.example' },
    topics: { maintenance: true, expiry: true, image: true, dataset: true },
    reminder_days: [7, 1],
    reachable: ['email'],
    protects_data: true,
    risk_acknowledged_at: null,
    ...changes,
});

const conflict = (allOff) => ({ response: { status: 409, data: { needs_acknowledgement: true, all_off: allOff } } });

async function shown(state = view()) {
    api.get.mockResolvedValue({ data: state });
    render(<NotificationSettings />);
    await screen.findByText('Where to reach you');
}

test('reminder days read naturally', () => {
    expect(daysBefore([7, 1])).toBe('7 days and 1 day before');
    expect(daysBefore([14, 7, 1])).toBe('14 days, 7 days and 1 day before');
    expect(daysBefore([3])).toBe('3 days before');
});

test('shows where and about what the user hears', async () => {
    await shown();
    expect(screen.getByText('alice@uni.example')).toBeInTheDocument();
    expect(screen.getByTestId('settings-email-switch')).toBeChecked();
    expect(screen.getByTestId('settings-matrix-input')).toHaveValue('@alice:matrix.uni.example');
    expect(screen.getByText(/7 days and 1 day before a local project directory is deleted/)).toBeInTheDocument();
    expect(screen.queryByTestId('notifications-off-banner')).not.toBeInTheDocument();
});

test('a topic switch is saved at once', async () => {
    await shown();
    api.put.mockResolvedValue({ data: view({ topics: { maintenance: true, expiry: true, image: false, dataset: true } }) });
    fireEvent.click(screen.getByTestId('settings-topic-image'));
    await waitFor(() => expect(screen.getByTestId('settings-topic-image')).not.toBeChecked());
    expect(api.put).toHaveBeenCalledWith('/api/notification-settings', { topics: { image: false } });
});

test('turning everything off asks first, and only goes ahead once the risk is acknowledged', async () => {
    await shown();
    api.put.mockRejectedValueOnce(conflict(true))
        .mockResolvedValueOnce({ data: view({ email: { enabled: false, address: 'alice@uni.example', available: true },
                                               reachable: [], protects_data: false }) });
    fireEvent.click(screen.getByTestId('settings-email-switch'));

    const dialog = await screen.findByTestId('risk-dialog');
    expect(within(dialog).getByText('Turn off all notifications?')).toBeInTheDocument();
    const confirm = within(dialog).getByTestId('risk-confirm');
    expect(confirm).toBeDisabled();
    fireEvent.click(within(dialog).getByTestId('risk-acknowledge'));
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);

    await screen.findByTestId('notifications-off-banner');
    expect(api.put).toHaveBeenLastCalledWith('/api/notification-settings',
        { email_enabled: false, acknowledge_risk: true });
    await waitFor(() => expect(screen.queryByTestId('risk-dialog')).not.toBeInTheDocument());
});

test('keeping notifications on changes nothing', async () => {
    await shown();
    api.put.mockRejectedValueOnce(conflict(false));
    fireEvent.click(screen.getByTestId('settings-topic-expiry'));
    const dialog = await screen.findByTestId('risk-dialog');
    expect(within(dialog).getByText('Turn off the warnings that protect your data?')).toBeInTheDocument();
    fireEvent.click(within(dialog).getByTestId('risk-keep'));
    await waitFor(() => expect(screen.queryByTestId('risk-dialog')).not.toBeInTheDocument());
    expect(api.put).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('settings-topic-expiry')).toBeChecked();
});

test('connecting Matrix: the bot sends a code, the user enters it', async () => {
    await shown();
    const pending = view({ matrix: { ...view().matrix, pending_id: '@alice:matrix.uni.example' } });
    const connected = view({ matrix: { ...view().matrix, id: '@alice:matrix.uni.example', enabled: true },
                             reachable: ['email', 'matrix'] });
    api.post.mockResolvedValueOnce({ data: pending }).mockResolvedValueOnce({ data: connected });

    fireEvent.click(screen.getByTestId('settings-matrix-connect'));
    expect(api.post).toHaveBeenCalledWith('/api/notification-settings/matrix',
        { matrix_id: '@alice:matrix.uni.example' });
    const code = await screen.findByTestId('settings-matrix-code');
    expect(screen.getByTestId('settings-matrix-verify')).toBeDisabled();
    fireEvent.change(code, { target: { value: '482193' } });
    fireEvent.click(screen.getByTestId('settings-matrix-verify'));

    expect(await screen.findByTestId('settings-matrix-id')).toHaveTextContent('@alice:matrix.uni.example');
    expect(api.post).toHaveBeenLastCalledWith('/api/notification-settings/matrix/verify', { code: '482193' });
});

test('a refused Matrix ID is explained', async () => {
    await shown();
    api.post.mockRejectedValueOnce({ response: { status: 502, data: { message: "WhaP's bot could not write to @x:y" } } });
    fireEvent.click(screen.getByTestId('settings-matrix-connect'));
    expect(await screen.findByTestId('settings-error')).toHaveTextContent("WhaP's bot could not write to @x:y");
});

test('the test message reports each channel', async () => {
    await shown();
    api.post.mockResolvedValueOnce({ data: { results: [
        { channel: 'email', address: 'alice@uni.example', ok: true },
        { channel: 'matrix', ok: false, error: 'The homeserver refused: 403 M_FORBIDDEN' },
    ] } });
    fireEvent.click(screen.getByTestId('settings-test'));
    const results = await screen.findAllByTestId('settings-test-result');
    expect(results[0]).toHaveTextContent('Sent to alice@uni.example');
    expect(results[1]).toHaveTextContent('Matrix: The homeserver refused: 403 M_FORBIDDEN');
});

test('without an address the user is told why', async () => {
    await shown(view({ email: { enabled: true, address: null, available: true }, reachable: [], protects_data: false,
                       matrix: { ...view().matrix, available: false } }));
    expect(screen.getByText(/Your account has no email address/)).toBeInTheDocument();
    expect(screen.getByText('This WhaP has no Matrix bot.')).toBeInTheDocument();
    expect(screen.getByTestId('settings-test')).toBeDisabled();
    expect(screen.getByTestId('notifications-off-banner')).toBeInTheDocument();
});
