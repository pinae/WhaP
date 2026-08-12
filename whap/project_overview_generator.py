import os

# --- Configuration ---

# 1. Define the introductory markdown text
intro_text = """# Project Overview: Fischer's Whale Pond (WhaP)

This project is a full-stack web application designed to provide users with a graphical interface for creating and managing project-specific Docker containers on a set of remote compute servers. It streamlines the process of deploying development environments, particularly for data science or machine learning tasks that require GPU access, by abstracting away the underlying command-line tools and server configurations. Users can log in, manage their projects and SSH keys, and then launch pre-configured container environments on specific servers with selected resources.

The application employs a modern technology stack, separating the frontend and backend for clear development and deployment. The backend is built with Python using the Flask web framework. It handles user authentication against an LDAP server and also supports local user accounts. All application data, such as projects, server details, and container instances, is stored in a PostgreSQL database, with SQLAlchemy serving as the Object-Relational Mapper (ORM). The core of the container deployment logic is managed by Ansible, with the Flask app dynamically generating and executing playbooks via the ansible-runner library. Real-time logging of the Ansible deployment process is pushed to the frontend using Flask-SocketIO over WebSockets.

The frontend is a single-page application (SPA) built with React. It utilizes the Material-UI component library to create a clean and responsive user interface that is consistent with modern design principles. Client-side routing is handled by React Router, while global state management, particularly for user authentication, is managed through React's Context API. The frontend communicates with the backend via a RESTful API for standard operations (fetching data, creating resources) and establishes a WebSocket connection to receive live log updates during container provisioning.

The project is organized into distinct backend and frontend directories. The backend/ directory follows a standard Flask application factory pattern, with subdirectories for routes, services (containing Ansible and LDAP logic), and models. The frontend/ directory is a typical Create React App structure, with components, pages, and contexts organized within the src/ folder. This clear separation allows for independent development, testing, and deployment of the two main parts of the application.

## Live updates of Ansible jobs

The live update mechanism provides real-time feedback by creating a communication channel from a background worker process to the user's browser. When a user action, like creating or deleting a container, is triggered in the frontend, an API call is made that creates an AnsibleJob record with a PENDING status in the database. A separate worker.py process periodically queries the database for these pending jobs. Upon finding one, it launches a run_job.py subprocess, which executes the corresponding Ansible playbook using the ansible-runner library. Crucially, the ansible-runner is configured with an event_handler callback function. For every event ansible-runner produces, such as a new line of log output, this callback is invoked. The callback sends the log data via an HTTP POST request to an internal /api/internal/job_update endpoint on the main server. This API endpoint then immediately relays the log line over a WebSocket connection using socketio.emit, sending it to a specific "room" that the user's browser has joined, allowing for the live display of the Ansible output.

When the ansible-runner completes its task, the worker process sends a final, distinct update to the /api/internal/job_update endpoint. This final payload includes the overall success or failure of the job and any resulting data, such as the container's new status (RUNNING or DELETED). The main application's API endpoint receives this report and performs the definitive database operations, such as changing a container's status or deleting its record entirely, and commits these changes. Only after the database transaction is successfully committed does the server emit a final ansible_job_completed message over the WebSocket. The frontend's ContainerDetail.js component listens for this specific event. Upon receiving it, it knows the background task is finished and either removes the component from the user's view (in the case of a successful deletion) or fetches the final, authoritative state of the container from the server to update the UI.

"""

# 2. List of files and folders to explicitly skip in the file tree and content output
exclude_patterns = {'.git', '__pycache__', 'node_modules', '.venv', 'dist', 'build',
                    'project_overview_generator.py',
                    'backend/migrations', 'backend/.env', 'backend/.flaskenv', 'backend/README.md', 'backend/migrations/',
                    'backend/Dockerfile', 'frontend/.env', 'frontend/.gitignore', 'frontend/README.json',
                    'frontend/yarn.lock', 'frontend/package-lock.json'}

# 3. Define the file extensions to include in the output
#    Files with these extensions will have their content printed.
allowed_extensions = {
    '.js', '.py', '.c', '.h', '.html', '.css', '.j2',
    '.txt', '.md', '.rst', '.json', '.yml', '.yaml'
}

# 4. Define the root directory of the project to analyze
#    An empty string '' means the current directory where the script is run.
root_dir = ''


# --- Script Logic ---

def get_file_tree(start_path, exclude):
    """Generates a string representation of the directory tree."""
    tree_lines = []
    for root, dirs, files in os.walk(start_path, topdown=True):
        # Exclude specified directories
        dirs[:] = [d for d in dirs if d not in exclude]

        level = root.replace(start_path, '').count(os.sep)
        indent = ' ' * 4 * level

        # Add the current directory to the tree, skip for root
        if level > 0 or (start_path == '' and os.path.basename(root)):
            tree_lines.append(f"{indent}|-- {os.path.basename(root)}/")

        sub_indent = ' ' * 4 * (level + 1)

        # Add the files in the current directory to the tree
        for f in sorted(files):
            if f not in exclude:
                tree_lines.append(f"{sub_indent}|-- {f}")

    return "\n".join(tree_lines)


def get_file_content(filepath):
    """Reads and returns the content of a file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file '{filepath}': {e}"


def get_language_from_extension(filename):
    """Determines the language for markdown code block from file extension."""
    extension_map = {
        '.js': 'javascript',
        '.py': 'python',
        '.c': 'c',
        '.h': 'c',
        '.html': 'html',
        '.css': 'css',
        '.j2': 'jinja',
        '.txt': 'text',
        '.md': 'markdown',
        '.rst': 'rst',
        '.json': 'json',
        '.yml': 'yaml',
        '.yaml': 'yaml'
    }
    _, ext = os.path.splitext(filename)
    return extension_map.get(ext.lower(), '')


def main():
    """Main function to generate and print the project overview."""

    # Start with the introductory text
    markdown_output = [intro_text]

    # --- File Tree ---
    markdown_output.append("## Directory and File Structure")
    markdown_output.append("```")

    project_root = root_dir if root_dir else os.getcwd()
    file_tree = get_file_tree(project_root, exclude_patterns)
    markdown_output.append(file_tree)

    markdown_output.append("```")

    # --- File Contents ---
    markdown_output.append("\n## Source Code Files")

    for root, dirs, files in os.walk(project_root, topdown=True):
        # Exclude specified directories from traversal
        dirs[:] = [d for d in dirs if d not in exclude_patterns]

        for filename in sorted(files):
            file_path = os.path.join(root, filename)
            relative_path = os.path.relpath(file_path, project_root).replace(os.sep, '/')
            # Check if the file itself should be excluded
            if relative_path in exclude_patterns or filename in exclude_patterns:
                continue

            _, ext = os.path.splitext(filename)
            if ext.lower() in allowed_extensions:
                file_path = os.path.join(root, filename)
                # Use forward slashes for cross-platform compatibility in markdown
                relative_path = os.path.relpath(file_path, project_root).replace(os.sep, '/')

                content = get_file_content(file_path)
                lang = get_language_from_extension(filename)

                markdown_output.append(f"\nBelow is the content of the file `{relative_path}`:")
                markdown_output.append(f"```{lang}\n{content}\n```")

    # Print the final markdown document to the console
    print("\n".join(markdown_output))


if __name__ == "__main__":
    main()