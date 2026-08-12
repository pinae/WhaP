"""Stats endpoint: injection hardening (WP2) and the pre-existing JSON-error path.

The endpoint interpolated the ``hostname`` path segment and the ``range`` query
param straight into InfluxDB Flux queries, so a crafted value could alter the
query (read other buckets/measurements). The endpoint must:
  * reject a hostname that is not a known ComputeServer (404), and
  * reject a malformed ``range`` (400),
in both cases *before* any InfluxDB client is constructed or queried.

InfluxDB is stubbed so no external service is required. The stub records whether
it was constructed and every Flux string it was asked to run, so the tests can
assert that rejected requests never reach Influx.

Also retained: bug #9 -- ``except json.JSONDecodeError or TypeError`` only caught
JSONDecodeError, so a non-string process value raised an uncaught TypeError and
the endpoint 500'd. The handler must fall back to an empty process list.
"""
import pytest

pytest.importorskip("influxdb_client")


class _FakeRecord:
    def __init__(self, value):
        self._value = value

    def get_value(self):
        return self._value


class _FakeTable:
    def __init__(self, records):
        self.records = records


class _RecordingQueryApi:
    def __init__(self, state, proc_value):
        self._state = state
        self._proc_value = proc_value

    def query(self, flux):
        self._state["queries"].append(flux)
        if "process_snapshot" in flux and self._proc_value is not None:
            return [_FakeTable([_FakeRecord(self._proc_value)])]
        return []


class _RecordingInflux:
    def __init__(self, state, proc_value):
        self._state = state
        self._proc_value = proc_value
        self.closed = False

    def query_api(self):
        return _RecordingQueryApi(self._state, self._proc_value)

    def close(self):
        self.closed = True


@pytest.fixture
def influx_state(monkeypatch):
    """Patch InfluxDBClient with a recorder. Returns a state dict tracking how
    many clients were constructed and every Flux query issued."""
    import app.routes.stats as stats_module

    state = {"constructed": 0, "queries": [], "proc_value": None}

    def _factory(*a, **k):
        state["constructed"] += 1
        return _RecordingInflux(state, state["proc_value"])

    monkeypatch.setattr(stats_module, "InfluxDBClient", _factory)
    return state


def test_stats_unknown_host_returns_404_without_querying(admin_client, influx_state):
    resp = admin_client.get("/api/stats/does-not-exist")
    assert resp.status_code == 404
    assert influx_state["constructed"] == 0
    assert influx_state["queries"] == []


def test_stats_injection_payload_rejected(admin_client, influx_state):
    # A Flux-breaking hostname must be rejected by the allowlist before any query.
    payload = 'x" or r._measurement == "secrets'
    resp = admin_client.get(f"/api/stats/{payload}")
    assert resp.status_code == 404
    assert influx_state["constructed"] == 0
    assert influx_state["queries"] == []


def test_stats_invalid_range_rejected(admin_client, influx_state, make_server):
    make_server(hostname="cuda01")
    resp = admin_client.get('/api/stats/cuda01?range=48h" or true')
    assert resp.status_code == 400
    assert influx_state["constructed"] == 0
    assert influx_state["queries"] == []


def test_stats_known_host_queries(admin_client, influx_state, make_server):
    make_server(hostname="cuda01")
    resp = admin_client.get("/api/stats/cuda01?range=24h")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    # Both the timeseries and process queries ran.
    assert influx_state["constructed"] == 1
    assert len(influx_state["queries"]) == 2
    # The validated host appears in the queries; the raw range is well-formed.
    assert all('r["host"] == "cuda01"' in q for q in influx_state["queries"])


def test_stats_handles_non_json_process_value(admin_client, influx_state, make_server):
    make_server(hostname="cuda01")
    # 123 is neither str nor bytes -> json.loads(123) raises TypeError.
    influx_state["proc_value"] = 123
    resp = admin_client.get("/api/stats/cuda01")
    assert resp.status_code == 200
    assert resp.get_json()["processes"] == []
