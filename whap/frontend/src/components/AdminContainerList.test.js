import { render, screen, fireEvent, within } from '@testing-library/react';
import AdminContainerList, { filterContainers, sortContainers, stringToColor } from './AdminContainerList';

const row = (id, user, server, ip, image, extra = {}) => ({
    id, user_display: `${user} (LDAP)`, username: user, project: `p${id}`, server, ip_address: ip, image,
    status: 'RUNNING', created_at: `2026-10-${String(10 + id).padStart(2, '0')}T08:00:00Z`, container_name: `c${id}`,
    ...extra,
});

const ROWS = [
    row(1, 'alice', 'tycho', '10.0.0.9', 'worker_local_ubuntu2404_ssh'),
    row(2, 'bob', 'kepler', '10.0.0.12', 'worker_synced_ubuntu2510_ssh', { status: 'STOPPED' }),
    row(3, 'carol', 'tycho', '10.0.1.2', 'worker_synced_ubuntu2510_ssh'),
];

const ids = () => screen.getAllByTestId('admin-container-row').map(r => r.getAttribute('data-container-id'));

function show(props = {}) {
    const handlers = { onStop: jest.fn(), onDelete: jest.fn(), onAddContainer: jest.fn(), onEditContainer: jest.fn() };
    const utils = render(<AdminContainerList containers={ROWS} stoppingContainerId={null} {...handlers} {...props} />);
    return { ...handlers, ...utils };
}

test('newest first by default', () => {
    show();
    expect(ids()).toEqual(['3', '2', '1']);
    expect(screen.getByTestId('admin-container-count')).toHaveTextContent('3 containers');
});

test('each column sorts both ways, IP addresses by their numbers', () => {
    show();
    fireEvent.click(screen.getByTestId('sort-ip'));
    expect(ids()).toEqual(['1', '2', '3']);  // .0.9 < .0.12 < .1.2
    fireEvent.click(screen.getByTestId('sort-ip'));
    expect(ids()).toEqual(['3', '2', '1']);
    fireEvent.click(screen.getByTestId('sort-user'));
    expect(ids()).toEqual(['1', '2', '3']);
    fireEvent.click(screen.getByTestId('sort-status'));
    expect(ids()[0]).toBe('1');  // RUNNING < STOPPED, ties by id
});

test('the filters narrow the list and say how much is shown', async () => {
    show();
    fireEvent.change(screen.getByTestId('filter-user'), { target: { value: 'CAR' } });
    expect(await screen.findByText('Showing 1 of 3')).toBeInTheDocument();
    expect(ids()).toEqual(['3']);
    fireEvent.click(screen.getByText('Clear filters'));
    fireEvent.change(screen.getByTestId('filter-ip'), { target: { value: '10.0.0.' } });
    expect(await screen.findByText('Showing 2 of 3')).toBeInTheDocument();
});

test('server and image are chosen from what the list contains', () => {
    show();
    fireEvent.mouseDown(within(screen.getByTestId('filter-server')).getByRole('combobox'));
    fireEvent.click(screen.getByRole('option', { name: 'tycho (2)' }));
    expect(ids()).toEqual(['3', '1']);
});

test('no match is said, not shown as an empty table', async () => {
    show();
    fireEvent.change(screen.getByTestId('filter-user'), { target: { value: 'nobody' } });
    expect(await screen.findByText('No container matches these filters.')).toBeInTheDocument();
});

test('the actions reach the page, also after it re-renders with new handlers', () => {
    const { onStop, rerender } = show();
    const newStop = jest.fn();
    rerender(<AdminContainerList containers={ROWS} stoppingContainerId={null} onStop={newStop}
                                 onDelete={jest.fn()} onAddContainer={jest.fn()} onEditContainer={jest.fn()} />);
    fireEvent.click(screen.getAllByTestId('admin-container-row')[0].querySelectorAll('button')[1]);
    expect(newStop).toHaveBeenCalledWith(3);
    expect(onStop).not.toHaveBeenCalled();
});

test('the helpers', () => {
    expect(filterContainers(ROWS, { user: '', ip: '', server: 'kepler', image: '' }).map(r => r.id)).toEqual([2]);
    expect(sortContainers(ROWS, 'created', 'asc').map(r => r.id)).toEqual([1, 2, 3]);
    expect(stringToColor('tycho')).toMatch(/^#[0-9a-f]{6}$/);
});
