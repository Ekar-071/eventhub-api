from .conftest import EVENT, signup


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_register_login_and_duplicates(client):
    r = client.post("/auth/register", json={"email": "a@b.fr", "password": "motdepasse1"})
    assert r.status_code == 201
    assert client.post("/auth/register", json={"email": "a@b.fr", "password": "motdepasse1"}).status_code == 409
    assert client.post("/auth/login", json={"email": "a@b.fr", "password": "mauvais-mdp"}).status_code == 401


def test_validation_errors(client):
    assert client.post("/auth/register", json={"email": "pas-un-email", "password": "motdepasse1"}).status_code == 422
    assert client.post("/auth/register", json={"email": "a@b.fr", "password": "court"}).status_code == 422


def test_create_requires_auth(client):
    assert client.post("/events", json=EVENT).status_code == 401


def test_event_crud_and_search(client):
    h = signup(client)
    created = client.post("/events", json=EVENT, headers=h)
    assert created.status_code == 201
    eid = created.json()["id"]
    assert client.get("/events", params={"q": "python"}).json()[0]["id"] == eid
    assert client.get("/events", params={"q": "inconnu"}).json() == []
    upd = client.put(f"/events/{eid}", json={**EVENT, "title": "Nouveau titre"}, headers=h)
    assert upd.json()["title"] == "Nouveau titre"
    assert client.delete(f"/events/{eid}", headers=h).status_code == 204
    assert client.get(f"/events/{eid}").status_code == 404


def test_only_owner_can_modify(client):
    owner, other = signup(client, "o@x.fr"), signup(client, "p@x.fr")
    eid = client.post("/events", json=EVENT, headers=owner).json()["id"]
    assert client.put(f"/events/{eid}", json=EVENT, headers=other).status_code == 403
    assert client.delete(f"/events/{eid}", headers=other).status_code == 403


def test_registration_rules(client):
    owner = signup(client, "o@x.fr")
    eid = client.post("/events", json=EVENT, headers=owner).json()["id"]
    u1, u2, u3 = (signup(client, f"u{i}@x.fr") for i in range(3))
    assert client.post(f"/events/{eid}/register", headers=u1).status_code == 201
    assert client.post(f"/events/{eid}/register", headers=u1).status_code == 409  # doublon
    assert client.post(f"/events/{eid}/register", headers=u2).status_code == 201
    assert client.post(f"/events/{eid}/register", headers=u3).status_code == 409  # complet
    assert client.get(f"/events/{eid}").json()["registrations_count"] == 2
