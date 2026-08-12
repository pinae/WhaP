from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required
from influxdb_client import InfluxDBClient
from .. import db
from ..models import ComputeServer
import json
import os
import re

stat_bp = Blueprint('stats', __name__)

# Configuration
INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")  # Docker internal name
# Token is secret: env-only, no in-source default (see config hardening / WP3).
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN")
INFLUX_ORG = os.getenv("INFLUX_ORG", "whap_org")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "metrics")

# A Flux relative-duration literal like "48h", "10m", "2d". Anything else is
# rejected so the ``range`` query param can never break out of the query string.
_RANGE_RE = re.compile(r'^\d+[smhdw]$')


def _host_filter(hosts):
    """Build a Flux predicate matching any of ``hosts``.

    Every value in ``hosts`` must be trusted (derived from a ComputeServer row),
    never raw request input -- this function does no escaping.
    """
    return " or ".join(f'r["host"] == "{h}"' for h in hosts)


def _timeseries_query(bucket, hosts, range_str):
    """Build the downsampled gpu/system time-series query.

    ``hosts`` is a list of validated ComputeServer host strings and ``range_str``
    a validated duration literal -- this function does no escaping and must never
    be handed untrusted input.
    """
    return f'''
    from(bucket: "{bucket}")
      |> range(start: -{range_str})
      |> filter(fn: (r) => {_host_filter(hosts)})
      |> filter(fn: (r) => r["_measurement"] == "gpu_stats" or r["_measurement"] == "system_stats")
      |> aggregateWindow(every: 2m, fn: mean, createEmpty: false)
      |> yield(name: "mean")
    '''


def _process_query(bucket, hosts):
    """Build the latest-process-snapshot query. ``hosts`` must be validated."""
    return f'''
    from(bucket: "{bucket}")
      |> range(start: -10m) 
      |> filter(fn: (r) => {_host_filter(hosts)})
      |> filter(fn: (r) => r["_measurement"] == "process_snapshot")
      |> last()
    '''


def _resolve_compute_server(hostname):
    """Resolve a requested host to a known ComputeServer, tolerating both the
    full hostname and the short (first DNS label) form.

    The frontend may request the short name (e.g. 'cuda04') while the DB stores
    the FQDN ('cuda04.ig17s.rub.de'), or vice versa. Matching is done in Python
    against the known-server list (a handful of rows), so the request string is
    only ever compared -- never interpolated into SQL or Flux. Returns the
    ComputeServer or None.
    """
    servers = db.session.scalars(db.select(ComputeServer)).all()
    for s in servers:  # exact match first
        if s.hostname == hostname:
            return s
    for s in servers:  # then short (first-label) match
        if s.hostname.split('.', 1)[0] == hostname:
            return s
    return None


def _query_hosts(server):
    """The trusted host tag values to match for a server: its FQDN and its short
    label. Covers metrics written with either convention (e.g. historical
    socket.gethostname() short tags and newer inventory_hostname FQDN tags)."""
    hosts = [server.hostname]
    short = server.hostname.split('.', 1)[0]
    if short != server.hostname:
        hosts.append(short)
    return hosts


@stat_bp.route('/stats/<hostname>', methods=['GET'])
@login_required
def get_server_stats(hostname):
    """
    Fetches aggregated time-series for charts and the latest process snapshot.
    """
    # Resolve the requested host against the known compute servers (authoritative
    # allowlist) BEFORE constructing an Influx client or building any query, so a
    # Flux-injecting hostname can never reach the query string. Accepts either the
    # FQDN or the short first-label form (the frontend may send either). Only
    # DB-sourced host strings are used in the query below.
    server = _resolve_compute_server(hostname)
    if not server:
        return jsonify({"message": "Unknown host"}), 404
    query_hosts = _query_hosts(server)

    # Validate the lookback window: only a Flux duration literal is allowed.
    range_str = request.args.get('range', '48h')
    if not _RANGE_RE.match(range_str):
        return jsonify({"message": "Invalid range format. Use e.g. '48h', '30m', '7d'."}), 400

    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    query_api = client.query_api()

    # 1. Fetch Time Series Data (Downsampled to every 2 minutes for smoothness)
    ts_query = _timeseries_query(INFLUX_BUCKET, query_hosts, range_str)

    # 2. Fetch Latest Process List
    proc_query = _process_query(INFLUX_BUCKET, query_hosts)

    # Execute Queries
    ts_tables = query_api.query(ts_query)
    proc_tables = query_api.query(proc_query)

    # Process Data
    response = {
        "timestamps": [],  # Shared X-Axis
        "cpu": [],
        "ram": [],
        "ram_total": 0,
        "gpus": {},  # { "0": { "util": [], "mem": [], "mem_total": 1234 } }
        "processes": []
    }

    # Helper to map timestamps to values for alignment
    temp_data = {}

    for table in ts_tables:
        for record in table.records:
            time_str = record.get_time().isoformat()
            if time_str not in temp_data:
                temp_data[time_str] = {"gpus": {}}

            field = record.get_field()
            value = record.get_value()
            measurement = record.get_measurement()

            if measurement == "system_stats":
                temp_data[time_str][field] = value
                if field == "ram_total_mb": response['ram_total'] = value  # Capture capacity

            elif measurement == "gpu_stats":
                gpu_idx = record.values.get("gpu_index")
                if gpu_idx not in temp_data[time_str]["gpus"]:
                    temp_data[time_str]["gpus"][gpu_idx] = {}
                temp_data[time_str]["gpus"][gpu_idx][field] = value
                # Capture max VRAM from the stream
                if gpu_idx not in response['gpus']: response['gpus'][gpu_idx] = {"util": [], "mem": [], "mem_total": 0}
                if field == "memory_total_mb": response['gpus'][gpu_idx]['mem_total'] = value

    # Sort by time and flatten
    sorted_times = sorted(temp_data.keys())
    response['timestamps'] = sorted_times

    for t in sorted_times:
        entry = temp_data[t]
        response['cpu'].append(entry.get('cpu_percent', 0))
        response['ram'].append(entry.get('ram_used_mb', 0))

        for gpu_idx, gpu_data in entry.get('gpus', {}).items():
            if gpu_idx not in response['gpus']:
                response['gpus'][gpu_idx] = {"util": [], "mem": [], "mem_total": 0}

            response['gpus'][gpu_idx]['util'].append(gpu_data.get('utilization', 0))
            response['gpus'][gpu_idx]['mem'].append(gpu_data.get('memory_used_mb', 0))

    # Parse Process List
    for table in proc_tables:
        for record in table.records:
            try:
                response['processes'] = json.loads(record.get_value())
            except (json.JSONDecodeError, TypeError):
                response['processes'] = []

    client.close()
    return jsonify(response)
