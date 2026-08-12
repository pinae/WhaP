import os
from flask import Blueprint, jsonify, send_from_directory, current_app, abort
from flask_login import login_required

docs_bp = Blueprint('docs', __name__)


def get_docs_dir():
    return current_app.config.get('DOCS_DIR')


@docs_bp.route('/docs/list', methods=['GET'])
@login_required
def list_docs():
    """Returns a list of available Markdown files (topics)."""
    docs_dir = get_docs_dir()
    if not os.path.isdir(docs_dir):
        return jsonify([]), 200

    files = []
    try:
        for filename in os.listdir(docs_dir):
            if filename.endswith('.md'):
                # formatting: "01_getting_started.md" -> "Getting Started"
                name_parts = os.path.splitext(filename)[0].split('_')
                # Remove leading numbers if present (e.g., 01, 02)
                if name_parts[0].isdigit():
                    name_parts.pop(0)
                display_name = ' '.join(word.capitalize() for word in name_parts)

                files.append({
                    'id': filename,
                    'title': display_name
                })
        # Sort by filename to maintain order (assuming 01_, 02_ prefixes)
        files.sort(key=lambda x: x['id'])
        return jsonify(files), 200
    except OSError as e:
        current_app.logger.error(f"Error listing docs: {e}")
        return jsonify({"message": "Failed to list documentation"}), 500


@docs_bp.route('/docs/content/<path:filename>', methods=['GET'])
@login_required
def get_doc_content(filename):
    """Serves the raw Markdown content."""
    docs_dir = get_docs_dir()
    if not filename.endswith('.md'):
        abort(400, "Invalid file type")
    try:
        return send_from_directory(docs_dir, filename)
    except FileNotFoundError:
        abort(404, "Documentation topic not found")


@docs_bp.route('/docs/images/<path:filename>', methods=['GET'])
@login_required
def get_doc_image(filename):
    """Serves images referenced in the Markdown."""
    images_dir = os.path.join(get_docs_dir(), 'images')
    try:
        return send_from_directory(images_dir, filename)
    except FileNotFoundError:
        abort(404, "Image not found")