import os
import re
import json
import time
import redis

from app import create_app, socketio, db
from app.config import check_critical_config, Config
from app.models import AnsibleJob
from app.job_queue import drain_batch

check_critical_config()

app_config_source = os.getenv('FLASK_CONFIG') or Config
app = create_app(app_config_source)

redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    decode_responses=True,
    # Detect and recover from silently-dropped idle connections instead of
    # blocking forever on a dead socket.
    socket_keepalive=True,
    health_check_interval=30,
)

JOB_UPDATES_QUEUE = 'job_updates_queue'
BATCH_MAX_SIZE = 50
# Block for a bounded window rather than forever, so an idle-dropped socket is
# noticed promptly and an empty return is just a normal idle tick.
BLOCK_TIMEOUT = 5


# --- Batch Processing Logic ---
def process_updates_in_batch(batch):
    """Process a batch of job updates pulled from the Redis queue.

    Persists final job/container state and relays log lines to the browser
    over Socket.IO. Runs inside an application context.
    """
    with app.app_context():
        for update in batch:
            job_id = update.get('job_id')
            event = update.get('event')

            if not job_id or not event:
                app.logger.warning(f"Skipping malformed update in batch: {update}")
                continue

            app.logger.info(f"{job_id}: {event['stdout'] if 'stdout' in event else event}")

            # Use a direct query for freshness
            job = db.session.execute(
                db.select(AnsibleJob).filter_by(id=job_id)
            ).scalar_one_or_none()
            if not job:
                app.logger.warning(f"Received job_update for non-existent job ID: {job_id}")
                continue

            container = job.container
            if not container:
                app.logger.error(f"Job {job_id} is orphaned. Deleting it.")
                db.session.delete(job)
                db.session.commit()
                continue

            if 'final_status' in event:
                _handle_final_status(job, container, event)
            elif 'stdout' in event:
                _relay_log_lines(container, event)


def _handle_final_status(job, container, event):
    """Commit the terminal state of a job/container and notify the client."""
    runner_status = event.get('runner_status')
    final_log = event.get('final_log', '')
    final_status = event.get('final_status', 'ERROR')
    extra_data = event.get('extra_data', {})

    app.logger.info(
        f"Processing final report for job {job.id}. "
        f"Runner status: '{runner_status}', Final Container Status: '{final_status}'"
    )

    try:
        # Special logic for successful deletions
        if final_status == 'DELETED' and runner_status == 'successful':
            app.logger.warning(f"Container {container.id} marked for deletion.")
            if container.static_address_id:
                container.static_address_id = None
            db.session.delete(container)
            db.session.delete(job)
        else:
            # Standard logic for other actions (create, stop, etc.)
            job.status = 'SUCCESSFUL' if runner_status == 'successful' else 'FAILED'
            job.log += f"\n--- Ansible STDOUT ---\n{final_log}\n--- End STDOUT ---"
            container.status = final_status
            if extra_data:
                for key, value in extra_data.items():
                    if hasattr(container, key):
                        setattr(container, key, value)

        db.session.commit()
        app.logger.info(f"Committed final state for container {container.id} and job {job.id}.")

        socketio.emit('ansible_job_completed',
                      {'container_id': container.id, 'status': final_status},
                      room=str(container.id))
        app.logger.info(f"Notified client of completion for container {container.id}.")

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"DB transaction failed for job {job.id}: {e}", exc_info=True)
        socketio.emit('ansible_job_completed',
                      {'container_id': container.id, 'status': 'ERROR'},
                      room=str(container.id))


def _relay_log_lines(container, event):
    """Stream cleaned-up Ansible stdout lines to the container's room."""
    for line in event['stdout'].splitlines():
        # Clean ANSI escape codes from the line
        clean_line = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
        if clean_line:
            socketio.emit('ansible_log',
                          {'container_id': container.id, 'line': clean_line},
                          room=str(container.id))


def queue_consumer():
    """Consume the Redis queue in small FIFO batches.

    Uses a bounded blocking pop so the loop wakes periodically: an empty return
    is a normal idle tick, a dropped connection is caught and retried, and a
    socket read-timeout is treated as benign rather than logged as an error.
    """
    app.logger.info("Starting job-update queue consumer...")
    while True:
        try:
            batch = drain_batch(redis_client, JOB_UPDATES_QUEUE,
                                BATCH_MAX_SIZE, BLOCK_TIMEOUT)
            if not batch:
                continue  # idle window elapsed with nothing queued

            updates = []
            for payload in batch:
                try:
                    updates.append(json.loads(payload))
                except (json.JSONDecodeError, TypeError):
                    app.logger.warning(f"Discarding malformed queue payload: {payload!r}")

            if updates:
                process_updates_in_batch(updates)

        except redis.exceptions.TimeoutError:
            # No item within the block window; not an error, just loop again.
            continue
        except redis.exceptions.ConnectionError as e:
            app.logger.warning(f"Redis connection lost in consumer; will reconnect: {e}")
            time.sleep(2)  # redis-py reconnects on the next command
        except redis.exceptions.RedisError as e:
            app.logger.error(f"Redis error in consumer thread: {e}")
            time.sleep(5)
        except Exception as e:
            app.logger.error(f"Error processing update from queue: {e}", exc_info=True)


def start_log_consumer():
    """Start the queue consumer as a Socket.IO background task."""
    socketio.start_background_task(queue_consumer)


# Start exactly one consumer per server process.
#   * Under gunicorn the module is imported (not __main__), so we start it here.
#     With a single web worker that means exactly one consumer.
#   * Under the dev server (`python run.py`) the Werkzeug reloader runs the
#     module twice; we start the consumer only in the reloaded child process
#     (WERKZEUG_RUN_MAIN == 'true') to avoid a duplicate.
if __name__ != '__main__':
    start_log_consumer()

if __name__ == '__main__':
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        start_log_consumer()
    # threading async mode + simple-websocket provide WebSocket support here.
    # debug is opt-in (FLASK_DEBUG=true) and must stay OFF in any deployment:
    # the Werkzeug debugger exposes an interactive console. Production runs under
    # gunicorn and never reaches this entrypoint.
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.logger.info("Starting Flask-SocketIO development server (threading mode).")
    socketio.run(app, host='0.0.0.0', port=5000, debug=debug, use_reloader=debug)
