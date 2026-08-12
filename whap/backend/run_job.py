import os
import sys
import json
import redis
from app import create_app, db
from app.models import AnsibleJob
from app.services import ansible_service

redis_client = redis.Redis(host=os.getenv('REDIS_HOST', 'localhost'), port=os.getenv('REDIS_PORT', 6379), db=0)

def send_update(job_id: int, event_data):
    payload = json.dumps({'job_id': job_id, 'event': event_data})
    redis_client.lpush('job_updates_queue', payload)

def main(job_id):
    app = create_app()
    with app.app_context():
        job = db.session.execute(db.select(AnsibleJob).filter_by(id=job_id)).scalar_one_or_none()
        if not job:
            print(f"WORKER ABORT: Job {job_id} not found in database.")
            return

        if job.status != 'RUNNING':
            print(f"WORKER ABORT: Job {job_id} is not in RUNNING state (current: {job.status}).")
            return

        print(
            f"WORKER START: Executing job {job.id} for action '{job.action}' on container {job.container_instance_id}")

        ## The actual ansible execution logic is in the service layer.
        # It takes the job object and a callback function for real-time logs.
        final_status, final_log, runner_status, extra_data = ansible_service.execute_ansible_job(
            job,
            lambda event: send_update(job.id, event) # Pass the HTTP callback handler for logs
        )

        # Report the final completion status to the main app.
        print(f"WORKER END: Job {job.id} finished with status '{runner_status}'.")
        send_update(job.id, {
            'final_status': final_status,
            'final_log': final_log,
            'runner_status': runner_status,
            'extra_data': extra_data
        })


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python run_job.py <job_id>")
        sys.exit(1)

    try:
        job_id_from_arg = int(sys.argv[1])
        main(job_id_from_arg)
    except ValueError:
        print("Error: Job ID must be an integer.")
        sys.exit(1)
    except Exception as e:
        # Catch any other unexpected errors during execution
        print(f"An unexpected error occurred in run_job.py for job {sys.argv[1]}: {e}")
        # Optionally, try to notify the main server of the failure
        try:
            send_update(int(sys.argv[1]),
                        {'final_status': 'failed', 'final_log': f'Worker script failed unexpectedly: {e}'})
        except:
            pass  # Ignore if notification fails
        sys.exit(1)