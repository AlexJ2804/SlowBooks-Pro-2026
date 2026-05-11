"""CRUD + protection tests for the classes table."""


def test_list_excludes_archived_by_default(client, seed_classes):
    seed_classes["Class B"].is_archived = True
    from sqlalchemy.orm import Session  # noqa: F401
    # commit through the client's session by re-fetching via the API
    # (the fixture's session is the same one the route reads from)
    cls_id = seed_classes["Class B"].id
    r = client.patch(f"/api/classes/{cls_id}", json={"is_archived": True})
    assert r.status_code == 200, r.text

    r = client.get("/api/classes")
    assert r.status_code == 200
    names = {c["name"] for c in r.json()}
    assert "Class A" in names
    assert "Uncategorized" in names
    assert "Class B" not in names


def test_list_includes_archived_when_requested(client, seed_classes):
    cls_id = seed_classes["Class B"].id
    client.patch(f"/api/classes/{cls_id}", json={"is_archived": True})

    r = client.get("/api/classes?include_archived=true")
    assert r.status_code == 200
    names = {c["name"] for c in r.json()}
    assert "Class B" in names


def test_create_class(client, seed_classes):
    r = client.post("/api/classes", json={"name": "Class C"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Class C"
    assert body["is_archived"] is False
    assert body["is_system_default"] is False


def test_create_duplicate_name_rejected(client, seed_classes):
    r = client.post("/api/classes", json={"name": "Class A"})
    assert r.status_code == 400
    assert "already exists" in r.json()["detail"]


def test_rename_class(client, seed_classes):
    cls_id = seed_classes["Class A"].id
    r = client.patch(f"/api/classes/{cls_id}", json={"name": "Renamed Class A"})
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed Class A"


def test_rename_to_existing_name_rejected(client, seed_classes):
    cls_id = seed_classes["Class A"].id
    r = client.patch(f"/api/classes/{cls_id}", json={"name": "Class B"})
    assert r.status_code == 400


def test_uncategorized_cannot_be_renamed(client, seed_classes):
    cls_id = seed_classes["Uncategorized"].id
    r = client.patch(f"/api/classes/{cls_id}", json={"name": "Default"})
    assert r.status_code == 403
    assert "Uncategorized" in r.json()["detail"]


def test_uncategorized_cannot_be_archived(client, seed_classes):
    cls_id = seed_classes["Uncategorized"].id
    r = client.patch(f"/api/classes/{cls_id}", json={"is_archived": True})
    assert r.status_code == 403


def test_archive_then_unarchive(client, seed_classes):
    cls_id = seed_classes["Class A"].id
    r = client.patch(f"/api/classes/{cls_id}", json={"is_archived": True})
    assert r.status_code == 200
    assert r.json()["is_archived"] is True

    r = client.patch(f"/api/classes/{cls_id}", json={"is_archived": False})
    assert r.status_code == 200
    assert r.json()["is_archived"] is False


def test_no_delete_endpoint_exists(client, seed_classes):
    cls_id = seed_classes["Class A"].id
    r = client.delete(f"/api/classes/{cls_id}")
    assert r.status_code == 405  # Method not allowed
