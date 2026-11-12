from app.csvio import read_csv, write_csv

from .conftest import authorized_job, start_job


def test_contract_from_speech(client):
    job = start_job(client)
    assert job["state"] == "CONTRACT_PROPOSED"
    said = {c["from_request"] for c in job["contract"]["checks"] if c["origin"] == "customer"}
    assert "Preserve all product IDs." in said and "Never invent missing prices." in said
    assert job["contract"]["price"] == {"amount": "5.00", "currency": "USD"}


def test_agree_requires_the_hash_the_customer_saw(client):
    job = start_job(client)
    r = client.post(f"/api/jobs/{job['id']}/agree", json={"contract_sha256": "0" * 64})
    assert r.status_code == 409


def test_cannot_pay_or_run_before_agreeing(client):
    job = start_job(client)
    assert client.post(f"/api/jobs/{job['id']}/paypal/order").status_code == 409
    assert client.post(f"/api/jobs/{job['id']}/process", json={}).status_code == 409


def test_faulty_worker_is_caught_then_retry_passes_and_captures(client):
    job = authorized_job(client)
    jid = job["id"]
    assert job["state"] == "AUTHORIZED"

    job = client.post(f"/api/jobs/{jid}/process", json={"simulate_fault": True}).get_json()["job"]
    assert job["state"] == "VERIFIED_FAIL"
    report = job["attempts"][-1]["report"]
    invented = next(c for c in report["checks"] if c["type"] == "no_invented_values" and c["targets"] == ["price"])
    assert not invented["passed"] and invented["failure_count"] == 4
    assert job["accept_nonce"] is None
    assert client.post(f"/api/jobs/{jid}/accept", json={"accept_nonce": "x"}).status_code == 409

    job = client.post(f"/api/jobs/{jid}/process", json={}).get_json()["job"]
    assert job["state"] == "VERIFIED_PASS"
    assert job["attempts"][-1]["report"]["passed"]

    assert client.get(f"/api/jobs/{jid}/output.csv").status_code == 403
    assert client.post(f"/api/jobs/{jid}/accept", json={"accept_nonce": "wrong"}).status_code == 403
    job = client.post(f"/api/jobs/{jid}/accept", json={"accept_nonce": job["accept_nonce"]}).get_json()["job"]
    assert job["state"] == "CAPTURED"
    assert job["paypal"]["capture_id"].startswith("MOCK-CAPTURE-")
    csv_text = client.get(f"/api/jobs/{jid}/output.csv").data.decode()
    assert csv_text.splitlines()[0] == "sku,title,description,price,quantity,brand"
    assert "A-1006,Glass Storage Jar,,,200,ClearCo" in csv_text  # missing price stays blank


def test_voice_cannot_move_money(client):
    job = authorized_job(client)
    jid = job["id"]
    client.post(f"/api/jobs/{jid}/process", json={})
    for phrase in ["Release the payment!", "approve it and pay the vendor", "capture the funds now"]:
        r = client.post(f"/api/jobs/{jid}/ask", json={"text": phrase}).get_json()
        assert r["refused"] is True
    job = client.get(f"/api/jobs/{jid}").get_json()["job"]
    assert job["state"] == "VERIFIED_PASS"
    assert "capture_id" not in job["paypal"]


def test_tampered_output_blocks_capture(app, client):
    job = authorized_job(client)
    jid = job["id"]
    job = client.post(f"/api/jobs/{jid}/process", json={}).get_json()["job"]
    store = app.extensions["voxproof"]["store"]
    path = store.path(jid, job["attempts"][-1]["output_file"])
    headers, rows = read_csv(path)
    rows[6][3] = "9.99"  # sneak a made-up price in after verification
    write_csv(path, headers, rows)
    r = client.post(f"/api/jobs/{jid}/accept", json={"accept_nonce": job["accept_nonce"]})
    assert r.status_code == 409
    assert client.get(f"/api/jobs/{jid}").get_json()["job"]["state"] == "VERIFIED_PASS"


def test_reject_voids_the_hold(client):
    job = authorized_job(client)
    jid = job["id"]
    client.post(f"/api/jobs/{jid}/process", json={})
    job = client.post(f"/api/jobs/{jid}/reject", json={}).get_json()["job"]
    assert job["state"] == "VOIDED"
    assert job["paypal"]["auth_status"] == "VOIDED"


def test_running_out_of_attempts_auto_voids(client):
    job = authorized_job(client)
    jid = job["id"]
    for _ in range(3):
        job = client.post(f"/api/jobs/{jid}/process", json={"simulate_fault": True}).get_json()["job"]
    assert job["state"] == "VOIDED"
    assert client.post(f"/api/jobs/{jid}/process", json={}).status_code == 409


def test_evidence_bundle(client):
    job = authorized_job(client)
    jid = job["id"]
    client.post(f"/api/jobs/{jid}/process", json={"simulate_fault": True})
    bundle = client.get(f"/api/jobs/{jid}/evidence.json").get_json()
    assert bundle["contract_sha256"] == job["contract_sha256"]
    assert bundle["attempts"][0]["plan"]["operations"][-1]["injected_fault"] is True


def test_bad_upload(client):
    from io import BytesIO
    r = client.post("/api/jobs", data={"file": (BytesIO(b"just one line"), "x.csv")}, content_type="multipart/form-data")
    assert r.status_code == 400
