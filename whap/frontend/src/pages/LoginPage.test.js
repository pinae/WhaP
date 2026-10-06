import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthContext } from '../contexts/AuthContext';
import LoginPage from './LoginPage';

function renderLogin(login) {
    return render(
        <AuthContext.Provider value={{ login }}>
            <MemoryRouter>
                <LoginPage />
            </MemoryRouter>
        </AuthContext.Provider>
    );
}

test('end-to-end test ids sit on the real input elements', () => {
    renderLogin(jest.fn());
    // On the <input> itself, not the MUI wrapper -- otherwise a browser test's
    // fill() would target a div.
    expect(screen.getByTestId('login-username').tagName).toBe('INPUT');
    expect(screen.getByTestId('login-password')).toHaveAttribute('type', 'password');
    expect(screen.getByTestId('login-submit').tagName).toBe('BUTTON');
});

test('submit stays disabled until both fields are filled', () => {
    renderLogin(jest.fn());
    const submit = screen.getByTestId('login-submit');
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByTestId('login-username'), { target: { value: 'usera' } });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByTestId('login-password'), { target: { value: 'pw' } });
    expect(submit).toBeEnabled();
});

test('a rejected login shows the server message', async () => {
    jest.spyOn(console, 'error').mockImplementation(() => {});  // the page logs the rejection
    const login = jest.fn().mockRejectedValue({ response: { data: { message: 'Invalid credentials' } } });
    renderLogin(login);
    fireEvent.change(screen.getByTestId('login-username'), { target: { value: 'usera' } });
    fireEvent.change(screen.getByTestId('login-password'), { target: { value: 'wrong' } });
    fireEvent.click(screen.getByTestId('login-submit'));

    expect(await screen.findByTestId('login-error')).toHaveTextContent('Invalid credentials');
    expect(login).toHaveBeenCalledWith('usera', 'wrong');
});

test('a successful login does not show an error', async () => {
    const login = jest.fn().mockResolvedValue(true);
    renderLogin(login);
    fireEvent.change(screen.getByTestId('login-username'), { target: { value: 'usera' } });
    fireEvent.change(screen.getByTestId('login-password'), { target: { value: 'right' } });
    fireEvent.click(screen.getByTestId('login-submit'));

    await waitFor(() => expect(login).toHaveBeenCalled());
    expect(screen.queryByTestId('login-error')).not.toBeInTheDocument();
});
