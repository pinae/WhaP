import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import api from '../services/api';
import LocalUserModal from './LocalUserModal';

jest.mock('../services/api', () => ({
    __esModule: true,
    default: { get: jest.fn(), post: jest.fn(), put: jest.fn() },
}));

afterEach(() => jest.clearAllMocks());

const field = (label) => screen.getByLabelText(new RegExp(`^${label}`));
const type = (label, value) => fireEvent.change(field(label), { target: { value } });

test('a new local user is saved with the email address their notifications go to', async () => {
    api.post.mockResolvedValue({ data: {} });
    const onSave = jest.fn();
    render(<LocalUserModal open onClose={jest.fn()} onSave={onSave} />);

    type('Username', 'carol');
    type('Email', ' carol@example.org ');
    type('Password', 'password123');
    type('Confirm Password', 'password123');
    fireEvent.click(screen.getByRole('button', { name: 'Create User' }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post).toHaveBeenCalledWith('/api/admin/users', {
        username: 'carol', email: 'carol@example.org', is_admin: false, password: 'password123',
    });
});

test('editing shows the stored address and can clear it', async () => {
    api.put.mockResolvedValue({ data: {} });
    render(<LocalUserModal open onClose={jest.fn()} onSave={jest.fn()}
                           userToEdit={{ id: 3, username: 'carol', email: 'carol@example.org', is_admin: false }} />);

    expect(field('Email')).toHaveValue('carol@example.org');
    type('Email', '');
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/api/admin/users/3', {
        username: 'carol', email: '', is_admin: false,
    }));
});
