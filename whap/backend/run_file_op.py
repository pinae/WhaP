import sys
import json
import traceback
from pathlib import Path
from app import create_app, db
from app.models import FileOperationJob
from app.services import local_file_service
from app.user_management import load_user_by_identifier


def main(job_id):
    app = create_app()
    with app.app_context():
        job = db.session.get(FileOperationJob, job_id)
        if not job:
            print(f"Error: Job ID {job_id} not found.")
            return

        print(f"Running job {job.id}: Operation '{job.operation}'")

        try:
            payload = json.loads(job.payload)
            log_output = []

            # --- Execute Operation ---
            if job.operation == 'create_directory':
                user = load_user_by_identifier(payload['user_identifier'])
                if not user: raise ValueError("User not found")
                local_file_service.create_directory(Path(payload['path']), user, mode=payload.get('mode'))
                log_output.append(f"Successfully created directory: {payload['path']}")

            elif job.operation == 'rename_directory':
                user = load_user_by_identifier(payload['user_identifier'])
                if not user: raise ValueError("User not found")
                local_file_service.rename_directory(Path(payload['old_path']), Path(payload['new_path']), user)
                log_output.append(f"Successfully renamed {payload['old_path']} to {payload['new_path']}")

            elif job.operation == 'delete_directory':
                local_file_service.delete_directory(Path(payload['path']))
                log_output.append(f"Successfully deleted directory: {payload['path']}")

            elif job.operation == 'ensure_lines_in_file':
                user = load_user_by_identifier(payload['user_identifier'])
                if not user: raise ValueError("User not found")
                local_file_service.ensure_lines_in_file(Path(payload['file_path']), payload['lines'], user)
                log_output.append(f"Successfully processed file: {payload['file_path']}")

            else:
                raise NotImplementedError(f"Operation '{job.operation}' is not implemented.")

            # --- Finalize Job ---
            job.status = 'SUCCESS'
            job.log = "\n".join(log_output)
            print(f"Job {job.id} completed successfully.")

        except Exception as e:
            print(f"Job {job.id} failed: {e}")
            job.status = 'FAILED'
            job.log = traceback.format_exc()

        finally:
            db.session.commit()


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python run_file_op.py <job_id>")
        sys.exit(1)

    try:
        job_id_arg = int(sys.argv[1])
        main(job_id_arg)
    except ValueError:
        print("Error: Job ID must be an integer.")
        sys.exit(1)
