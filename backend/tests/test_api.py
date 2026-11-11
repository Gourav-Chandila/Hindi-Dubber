"""Upload protocol used by the Android app (no ML needed)."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HD_DATA_DIR", str(tmp_path))
    import app.config
    import app.main

    importlib.reload(app.config)
    main = importlib.reload(app.main)
    submitted = []
    monkeypatch.setattr(main.worker, "submit", lambda jid: submitted.append(jid))
    c = TestClient(main.app)
    c.submitted = submitted
    return c


def test_resumable_upload_flow(client):
    data = b"x" * 1000
    uid = client.post("/uploads", json={"filename": "a.mp4", "size": 1000}).json()["upload_id"]
    assert client.put(f"/uploads/{uid}?offset=0", content=data[:400]).json()["received"] == 400
    # Wrong offset (e.g. retry after network drop) -> 409 with resume point.
    r = client.put(f"/uploads/{uid}?offset=0", content=data[:400])
    assert r.status_code == 409 and r.json()["detail"]["received"] == 400
    assert client.get(f"/uploads/{uid}").json()["received"] == 400
    # Completing early is refused.
    assert client.post(f"/uploads/{uid}/complete").status_code == 409
    client.put(f"/uploads/{uid}?offset=400", content=data[400:])
    jid = client.post(f"/uploads/{uid}/complete").json()["job_id"]
    assert client.submitted == [jid]
    job = client.get(f"/jobs/{jid}").json()
    assert job["filename"] == "a.mp4"
    assert client.get(f"/jobs/{jid}/result").status_code == 404


def test_rejects_oversize(client):
    r = client.post("/uploads", json={"filename": "a.mp4", "size": 10**13})
    assert r.status_code == 413
