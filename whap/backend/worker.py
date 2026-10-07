import time
import subprocess
import sys
from app import create_app, db
from app.models import AnsibleJob, FileOperationJob

# A file operation that takes longer than this is stuck (an LDAP lookup that
# never returns, a hung NFS mount); it is failed so the queue moves on.
FILE_OP_TIMEOUT = 600


def next_ansible_job():
    """The oldest pending job whose container has no job running.

    Jobs for one container run one at a time, in the order they were queued:
    a delete sent while the create is still running must wait for it, or the
    create could finish last and leave a container no record knows about.
    Jobs for different containers still run side by side.
    """
    busy = db.select(AnsibleJob.container_instance_id).where(AnsibleJob.status == 'RUNNING')
    return db.session.scalar(
        db.select(AnsibleJob)
        .where(AnsibleJob.status == 'PENDING', AnsibleJob.container_instance_id.not_in(busy))
        .order_by(AnsibleJob.created_at, AnsibleJob.id)
    )


def next_file_op():
    return db.session.scalar(
        db.select(FileOperationJob).filter_by(status='PENDING')
        .order_by(FileOperationJob.created_at, FileOperationJob.id)
    )


def run_file_op(job):
    """Run one file operation to completion before the next.

    In order, because they depend on each other: a project's rename must not
    overtake its creation. They take seconds, so waiting holds up little.
    """
    job.status = 'RUNNING'
    db.session.commit()
    try:
        subprocess.run([sys.executable, 'run_file_op.py', str(job.id)], timeout=FILE_OP_TIMEOUT)
    except subprocess.TimeoutExpired:
        db.session.refresh(job)
        job.status = 'FAILED'
        job.log = (job.log or '') + f"\nKilled after {FILE_OP_TIMEOUT}s."
        db.session.commit()
    # run_file_op.py committed the outcome from its own process.
    db.session.expire_all()


def fail_interrupted_jobs():
    """Fail the jobs a previous worker left RUNNING.

    Their processes died with it. Left RUNNING, an Ansible job would hold up
    every later job for its container -- its delete included -- for good.
    """
    for model in (AnsibleJob, FileOperationJob):
        for job in db.session.scalars(db.select(model).filter_by(status='RUNNING')):
            job.status = 'FAILED'
            job.log = (job.log or '') + "\nInterrupted: the worker restarted while this job ran."
            print(f"Marked interrupted {model.__name__} {job.id} as FAILED.")
    db.session.commit()


def run_worker_manager():
    app = create_app()
    with app.app_context():
        print("Starting Worker Manager...")
        fail_interrupted_jobs()
        while True:
            # Check for Ansible jobs
            ansible_job = next_ansible_job()
            if ansible_job:
                print(f"Found pending Ansible job {ansible_job.id}, launching subprocess...")
                ansible_job.status = 'RUNNING'
                db.session.commit()
                subprocess.Popen([sys.executable, 'run_job.py', str(ansible_job.id)])
                time.sleep(.1)  # Pause briefly to allow subprocess to start
                continue  # Immediately check for another job

            # Check for File Operation jobs
            file_op_job = next_file_op()
            if file_op_job:
                print(f"Running File Operation job {file_op_job.id}...")
                run_file_op(file_op_job)
                continue

            # If no jobs were found, wait before polling again. Expire what this
            # session has cached, so the next poll sees what the job processes wrote.
            db.session.expire_all()
            time.sleep(2)


if __name__ == '__main__':
    run_worker_manager()
