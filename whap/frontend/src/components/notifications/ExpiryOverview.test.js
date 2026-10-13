import { render, screen, fireEvent } from '@testing-library/react';
import api from '../../services/api';
import ExpiryOverview from './ExpiryOverview';

jest.mock('../../services/api', () => ({ __esModule: true, default: { get: jest.fn() } }));

test('admins see the schedule, the next reminders and the ones sent', async () => {
    const onOpen = jest.fn();
    const recent = { id: 9, kind: 'expiry', status: 'sent', title: 'Your project “ocr” on tycho expires in 5 days',
                     sent_at: '2030-10-12T08:00:00Z', deliveries: { sent: 1, pending: 0, failed: 0 } };
    api.get.mockImplementation(url => Promise.resolve({ data: url.endsWith('/preview')
        ? { sample: true, username: 'carol', subject: '[WhaP] Your project “ocr” expires in 5 days', html: '<p>Hello carol</p>' }
        : { days: [7, 1], recent: [recent], upcoming: [
            { container_id: 1, user: 'carol (Local)', project: 'ocr', server: 'tycho', ttl_date: '2030-10-17T00:00:00Z',
              step: 1, sends_at: '2030-10-16T00:00:00Z' }] } }));
    render(<ExpiryOverview timeZone="UTC" onOpen={onOpen} />);

    expect(await screen.findByText(/Sent 7 days and 1 day before/)).toBeInTheDocument();
    expect(screen.getByTestId('expiry-upcoming')).toHaveTextContent('carol (Local)ocrtychoThu 17 Oct1 day beforeWed 16 Oct, 00:00');
    fireEvent.click(screen.getByTestId('expiry-recent'));
    expect(onOpen).toHaveBeenCalledWith(recent);

    fireEvent.click(screen.getByTestId('expiry-preview'));
    expect(await screen.findByText('Hello carol')).toBeInTheDocument();
    expect(screen.getByText(/As carol, whose container expires next/)).toBeInTheDocument();
});
