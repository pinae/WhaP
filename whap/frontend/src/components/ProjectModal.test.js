import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import api from '../services/api';
import ProjectModal from './ProjectModal';

jest.mock('../services/api', () => ({
    __esModule: true,
    default: { get: jest.fn(), post: jest.fn(), put: jest.fn() },
}));

afterEach(() => jest.clearAllMocks());

function createProject(name) {
    fireEvent.change(screen.getByTestId('project-name-input'), { target: { value: name } });
    fireEvent.click(screen.getByTestId('project-modal-submit'));
}

test('creating a project hands the saved project to the caller and closes', async () => {
    const saved = { id: 7, name: 'thesis', owner_display: 'usera (LDAP)' };
    api.post.mockResolvedValue({ data: saved });
    const onProjectSaved = jest.fn();
    const onClose = jest.fn();

    render(<ProjectModal open onClose={onClose} onProjectSaved={onProjectSaved} />);
    createProject('thesis');

    await waitFor(() => expect(onProjectSaved).toHaveBeenCalledWith(saved));
    expect(api.post).toHaveBeenCalledWith('/api/projects', { name: 'thesis', shares: [] });
    expect(onClose).toHaveBeenCalled();
    expect(screen.queryByTestId('project-modal-error')).not.toBeInTheDocument();
});

test('a server rejection is shown and the dialog stays open', async () => {
    jest.spyOn(console, 'error').mockImplementation(() => {});  // the modal logs the rejection
    api.post.mockRejectedValue({ response: { data: { message: "Project name 'thesis' already exists" } } });
    const onProjectSaved = jest.fn();
    const onClose = jest.fn();

    render(<ProjectModal open onClose={onClose} onProjectSaved={onProjectSaved} />);
    createProject('thesis');

    expect(await screen.findByTestId('project-modal-error')).toHaveTextContent('already exists');
    expect(onProjectSaved).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
});

test('an invalid name is rejected before any request', () => {
    render(<ProjectModal open onClose={jest.fn()} onProjectSaved={jest.fn()} />);
    createProject('../escape');

    expect(screen.getByTestId('project-modal-error')).toHaveTextContent('must start with a letter or number');
    expect(api.post).not.toHaveBeenCalled();
});
