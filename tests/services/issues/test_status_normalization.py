from app.services.issues.utils import normalize_issue_status


def test_offen_normalized_to_open_status():
    status_key, status_label = normalize_issue_status("Offen")
    assert status_key == "open"
    assert status_label == "Open"
