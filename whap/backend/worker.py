import time
import subprocess
import sys
from app import create_app, db
from app.models import AnsibleJob, FileOperationJob


def run_worker_manager():
    app = create_app()
    with app.app_context():
        print("Starting Worker Manager...")
        while True:
            # Check for Ansible jobs
            ansible_job = AnsibleJob.query.filter_by(status='PENDING').order_by(AnsibleJob.created_at).first()
            if ansible_job:
                print(f"Found pending Ansible job {ansible_job.id}, launching subprocess...")
                ansible_job.status = 'RUNNING'
                db.session.commit()
                subprocess.Popen([sys.executable, 'run_job.py', str(ansible_job.id)])
                time.sleep(.1)  # Pause briefly to allow subprocess to start
                continue  # Immediately check for another job

            # Check for File Operation jobs
            file_op_job = FileOperationJob.query.filter_by(status='PENDING').order_by(
                FileOperationJob.created_at).first()
            if file_op_job:
                print(f"Found pending File Operation job {file_op_job.id}, launching subprocess...")
                file_op_job.status = 'RUNNING'
                db.session.commit()
                subprocess.Popen([sys.executable, 'run_file_op.py', str(file_op_job.id)])
                time.sleep(.1)  # Pause briefly
                continue

            # If no jobs were found, wait before polling again
            time.sleep(2)


if __name__ == '__main__':
    run_worker_manager()