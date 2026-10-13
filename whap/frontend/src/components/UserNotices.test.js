import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import api from '../services/api';
import UserNotices from './UserNotices';

jest.mock('../services/api', () => ({
    __esModule: true,
    default: { get: jest.fn(), post: jest.fn() },
}));

afterEach(() => jest.clearAllMocks());

const NOTICES = [
    { kind: 'maintenance', id: 1, title: 'tycho restarts on Tue 20 Oct, 08:00', containers: ['ocr', 'thesis'],
      impact: 'your containers are stopped before the restart.' },
    { kind: 'expiry', container_id: 42, project: 'ocr', server: 'tycho', ttl_date: 'Thursday, 15 October 2026',
      expires_in: 'tomorrow', urgent: true },
];
const CONTAINERS = [{ id: 42, project: 'ocr', server: 'tycho' }];

function Where() {
    const location = useLocation();
    return <span data-testid="where">{location.search}</span>;
}

function show(url = '/user', containers = CONTAINERS, onProlonged = jest.fn()) {
    const tree = (list) => (
        <MemoryRouter initialEntries={[url]}>
            <Routes><Route path="/user" element={<><UserNotices containers={list} onProlonged={onProlonged} /><Where /></>} /></Routes>
        </MemoryRouter>);
    render(tree(containers));
    return onProlonged;
}

test('maintenance and expiring projects are shown above the panel', async () => {
    api.get.mockResolvedValue({ data: NOTICES });
    show();
    expect(await screen.findByTestId('notice-maintenance'))
        .toHaveTextContent('tycho restarts on Tue 20 Oct, 08:00. What happens: your containers are stopped');
    expect(screen.getByTestId('notice-expiry')).toHaveTextContent('“ocr” on tycho expires tomorrow (Thursday, 15 October 2026)');
});

test('prolonging from a notice asks first, then reports back', async () => {
    api.get.mockResolvedValue({ data: NOTICES });
    api.post.mockResolvedValue({ data: {} });
    const onProlonged = show();
    fireEvent.click(await screen.findByText('Prolong 4 weeks'));
    expect(screen.getByTestId('prolong-dialog')).toHaveTextContent('Prolong “ocr” by four weeks?');
    fireEvent.click(screen.getByTestId('prolong-confirm'));
    expect(await screen.findByTestId('notice-result')).toHaveTextContent('“ocr” now expires four weeks later.');
    expect(api.post).toHaveBeenCalledWith('/api/containers/42/prolong');
    expect(onProlonged).toHaveBeenCalled();
});

test('the link in an expiry reminder opens the question, and the link is forgotten after', async () => {
    api.get.mockResolvedValue({ data: [] });
    show('/user?tab=containers&prolong=42');
    expect(await screen.findByTestId('prolong-dialog')).toHaveTextContent('Prolong “ocr” by four weeks?');
    fireEvent.click(screen.getByText('Not now'));
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('?tab=containers'));
    expect(screen.getByTestId('where')).not.toHaveTextContent('prolong');
    expect(api.post).not.toHaveBeenCalled();
});

test('a link to someone else\'s container is explained', async () => {
    api.get.mockResolvedValue({ data: [] });
    show('/user?prolong=99');
    expect(await screen.findByTestId('notice-result')).toHaveTextContent('not one of yours');
});

test('a refused prolong says why', async () => {
    api.get.mockResolvedValue({ data: NOTICES });
    api.post.mockRejectedValue({ response: { data: { message: 'The TTL can be at most 12 months ahead' } } });
    show();
    fireEvent.click(await screen.findByText('Prolong 4 weeks'));
    fireEvent.click(screen.getByTestId('prolong-confirm'));
    expect(await screen.findByTestId('notice-result')).toHaveTextContent('at most 12 months ahead');
});
