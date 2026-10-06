import { render, screen, act } from '@testing-library/react';
import io from 'socket.io-client';
import api from '../services/api';
import ContainerDetails from './ContainerDetail';

jest.mock('../services/api', () => ({
    __esModule: true,
    default: { get: jest.fn(), post: jest.fn(), delete: jest.fn() },
}));

jest.mock('socket.io-client', () => ({ __esModule: true, default: jest.fn() }));

// A socket whose server-side events the test fires by hand. The implementation
// is installed per test: CRA's Jest preset runs with resetMocks, which clears
// implementations given in a jest.mock factory before every test.
let socket;
beforeEach(() => {
    io.mockImplementation(() => {
        socket = { handlers: {}, emit: jest.fn(), disconnect: jest.fn() };
        socket.on = (event, fn) => { socket.handlers[event] = fn; };
        return socket;
    });
});

const serverSends = (event, payload) => act(() => socket.handlers[event](payload));

const base = {
    id: 42, project: 'thesis', image: 'worker_local_ubuntu2510_ssh', server: 'tycho',
    gpus: '0', username: 'usera', ip_address: '10.0.0.17', server_ssh_port: 22,
    created_at: '2026-10-06T10:00:00Z', ansible_log: 'PLAY RECAP stored',
};

function renderCard(container, handlers = {}) {
    return render(<ContainerDetails container={container}
                                    onUpdate={handlers.onUpdate || jest.fn()}
                                    onDelete={handlers.onDelete || jest.fn()}/>);
}

test('the card exposes its identity and state as data attributes', () => {
    renderCard({ ...base, status: 'RUNNING' });
    const card = screen.getByTestId('container-card');
    expect(card).toHaveAttribute('data-container-id', '42');
    expect(card).toHaveAttribute('data-project', 'thesis');
    expect(card).toHaveAttribute('data-image', 'worker_local_ubuntu2510_ssh');
    expect(card).toHaveAttribute('data-status', 'RUNNING');
    expect(screen.getByTestId('container-ip')).toHaveTextContent('10.0.0.17');
    expect(screen.getByTestId('container-ssh-command')).toHaveTextContent('ssh usera@10.0.0.17');
});

test('a running container opens no socket and its log is the stored one', () => {
    renderCard({ ...base, status: 'RUNNING' });
    expect(io).not.toHaveBeenCalled();
    expect(screen.queryByTestId('container-log')).not.toBeInTheDocument();  // collapsed

    act(() => screen.getByTestId('container-logs-toggle').click());
    const log = screen.getByTestId('container-log');
    expect(log).toHaveAttribute('data-log-source', 'stored');
    expect(log).toHaveAttribute('data-live-lines', '0');
    expect(log).toHaveTextContent('PLAY RECAP stored');
});

test('streamed lines are counted and replace the stored log', () => {
    renderCard({ ...base, status: 'STARTING', ip_address: null });
    expect(io).toHaveBeenCalledTimes(1);

    serverSends('connect');
    expect(socket.emit).toHaveBeenCalledWith('join_log_room', { container_id: '42' });

    const log = screen.getByTestId('container-log');  // auto-expanded while a job runs
    expect(log).toHaveAttribute('data-log-source', 'stored');

    serverSends('ansible_log', { container_id: 42, line: 'PLAY [tycho]' });
    serverSends('ansible_log', { container_id: 42, line: 'TASK [Start container]' });
    serverSends('ansible_log', { container_id: 99, line: 'another container' });

    expect(log).toHaveAttribute('data-log-source', 'live');
    expect(log).toHaveAttribute('data-live-lines', '2');  // the other room's line is ignored
    expect(log).toHaveTextContent('TASK [Start container]');
    expect(log).not.toHaveTextContent('another container');
});

test('job completion fetches the final state', async () => {
    const onUpdate = jest.fn();
    api.get.mockResolvedValue({ data: { ...base, status: 'RUNNING' } });
    renderCard({ ...base, status: 'STARTING' }, { onUpdate });

    await serverSends('ansible_job_completed', { container_id: 42, status: 'RUNNING' });

    expect(api.get).toHaveBeenCalledWith('/api/containers/42');
    expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({ status: 'RUNNING' }));
});

test('a confirmed deletion removes the card instead of re-fetching', async () => {
    const onDelete = jest.fn();
    renderCard({ ...base, status: 'DELETING' }, { onDelete });

    await serverSends('ansible_job_completed', { container_id: 42, status: 'DELETED' });

    expect(onDelete).toHaveBeenCalledWith(42);
    expect(api.get).not.toHaveBeenCalled();
});
