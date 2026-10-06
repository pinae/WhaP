import { render, screen, fireEvent, within, waitFor } from '@testing-library/react';
import api from '../services/api';
import { AuthContext } from '../contexts/AuthContext';
import ContainerForm from './ContainerForm';

jest.mock('../services/api', () => ({
    __esModule: true,
    default: { get: jest.fn(), post: jest.fn(), put: jest.fn() },
}));

let projects;

beforeEach(() => {
    projects = [{ id: 1, name: 'existing' }];
    const responses = {
        '/api/sshkeys': [{ id: 3, name: 'laptop' }],
        '/api/permissions/my-available-servers': [{ id: 5, hostname: 'tycho', gpu_count: 1, cpu_limit: null }],
        '/api/permissions/my-available-images': [
            { id: 'worker_local_ubuntu2510_ssh', name: 'worker_local_ubuntu2510_ssh' },
            { id: 'worker_synced_ubuntu2510_ssh', name: 'worker_synced_ubuntu2510_ssh' },
        ],
        '/api/shared-volumes': [],
        '/api/my-networks': [],
        '/api/my-static_addresses': [],
    };
    // /api/projects reads the live list, so a POST is visible to the re-fetch
    // that follows it -- as it is against the real backend.
    api.get.mockImplementation(async (url) => ({ data: url === '/api/projects' ? projects : responses[url] }));
});

afterEach(() => jest.clearAllMocks());

const USER = { id: 'ldap:usera', username: 'usera', user_type: 'ldap', is_admin: false };

function renderForm() {
    return render(
        <AuthContext.Provider value={{ user: USER }}>
            <ContainerForm onContainerCreated={jest.fn()} />
        </AuthContext.Provider>
    );
}

// MUI Selects open on mouseDown of the element carrying role="combobox".
function openSelect(testId) {
    fireEvent.mouseDown(screen.getByTestId(testId));
    return within(screen.getByRole('listbox'));
}

test('selects expose name-keyed options to end-to-end tests', async () => {
    renderForm();

    const projectSelect = await screen.findByTestId('container-project-select');
    expect(projectSelect).toHaveAttribute('role', 'combobox');
    await waitFor(() => expect(projectSelect).not.toHaveAttribute('aria-disabled', 'true'));
    expect(openSelect('container-project-select').getByTestId('container-project-option-existing')).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('listbox'), { key: 'Escape' });

    const images = openSelect('container-image-select');
    expect(images.getByTestId('container-image-option-worker_local_ubuntu2510_ssh')).toBeInTheDocument();
    expect(images.getByTestId('container-image-option-worker_synced_ubuntu2510_ssh')).toBeInTheDocument();
});

test('a single available server is pre-selected and its GPUs are offered', async () => {
    renderForm();
    expect(await screen.findByTestId('container-server-select')).toHaveTextContent('tycho');
    expect(await screen.findByTestId('container-gpu-0')).toHaveAttribute('type', 'checkbox');
    expect(screen.queryByTestId('container-gpu-1')).not.toBeInTheDocument();
});

test('a project created with the + button is selected in the form', async () => {
    // Regression: the form passed onProjectCreated, a prop the modal does not
    // have. The POST succeeded, then calling the missing onProjectSaved threw,
    // the dialog reported "Failed to save project", and the new project never
    // reached the dropdown.
    api.post.mockImplementation(async (url, body) => {
        const created = { id: 2, name: body.name };
        projects = [...projects, created];
        return { data: created };
    });
    renderForm();
    await screen.findByTestId('container-project-select');

    fireEvent.click(screen.getByTestId('container-project-add'));
    fireEvent.change(screen.getByTestId('project-name-input'), { target: { value: 'fresh' } });
    fireEvent.click(screen.getByTestId('project-modal-submit'));

    await waitFor(() => expect(screen.getByTestId('container-project-select')).toHaveTextContent('fresh'));
    expect(screen.queryByTestId('project-modal-error')).not.toBeInTheDocument();
    expect(api.post).toHaveBeenCalledWith('/api/projects', { name: 'fresh', shares: [] });
});
