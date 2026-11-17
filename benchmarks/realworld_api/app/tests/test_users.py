"""Users & auth: R2-R7, R21-R23."""
import re

import pytest


def reg(client, **over):
    u = {"username": "alice_x", "email": "alice_x@example.com", "password": "pw"}
    u.update(over)
    return client.post("/users", {"user": u})


def test_register_ok_r2(client):
    r = reg(client, username="reg_ok", email="reg_ok@example.com")
    assert r.status == 201
    u = r.json["user"]
    assert set(u) == {"email", "token", "username", "bio", "image"}
    assert u["username"] == "reg_ok" and u["bio"] is None and u["image"] is None and u["token"]


@pytest.mark.parametrize("field", ["username", "email", "password"])
def test_register_missing_blank_r3(client, field):
    body = {"username": "v1", "email": "v1@example.com", "password": "pw"}
    del body[field]
    r = client.post("/users", {"user": body})
    assert r.status == 422 and field in r.json["errors"]
    body[field] = "  "
    r = client.post("/users", {"user": body})
    assert r.status == 422 and field in r.json["errors"]


def test_register_bad_email_and_body_r3(client):
    r = reg(client, email="not-an-email")
    assert r.status == 422 and r.json["errors"]["email"] == ["is invalid"]
    assert client.post("/users", {}).status == 422
    assert client.post("/users", {"user": "x"}).status == 422
    r = client.call("POST", "/users", raw=b"{nope")
    assert r.status == 422 and "errors" in r.json


def test_register_duplicates_r4(client):
    assert reg(client, username="dup1", email="dup1@example.com").status == 201
    r = reg(client, username="dup1", email="other1@example.com")
    assert r.status == 409 and r.json == {"errors": {"username": ["has already been taken"]}}
    r = reg(client, username="other1", email="DUP1@example.com")
    assert r.status == 409 and r.json == {"errors": {"email": ["has already been taken"]}}


def test_login_r5(client, user):
    r = client.post("/users/login", {"user": {"email": user["email"], "password": user["password"]}})
    assert r.status == 200 and r.json["user"]["username"] == user["username"] and r.json["user"]["token"]
    r = client.post("/users/login", {"user": {"email": user["email"], "password": "wrong"}})
    assert r.status == 401 and "errors" in r.json
    r = client.post("/users/login", {"user": {"email": "nobody@example.com", "password": "x"}})
    assert r.status == 401
    assert client.post("/users/login", {"user": {"email": user["email"]}}).status == 422
    assert client.post("/users/login", {}).status == 422


def test_auth_failures_r6(client, user):
    r = client.get("/user")
    assert r.status == 401 and r.json == {"errors": {"token": ["is missing"]}}
    assert client.get("/user", token="bad.token.here").status == 401
    r = client.get("/user", headers={"Authorization": "Bearer " + user["token"]})
    assert r.status == 401
    r = client.get("/user", headers={"Authorization": user["token"]})
    assert r.status == 401
    assert client.get("/user", token=user["token"]).status == 200
    # invalid token on an optional-auth endpoint
    assert client.get("/articles", token="bad").status == 401
    assert client.get("/articles").status == 200


def test_get_current_user_r7(client, user):
    r = client.get("/user", token=user["token"])
    assert r.status == 200
    assert r.json["user"]["email"] == user["email"]


def test_update_user_r7(client, user, make_user):
    t = user["token"]
    r = client.put("/user", {"user": {"bio": "hi", "image": "http://i/x.png"}}, token=t)
    assert r.status == 200 and r.json["user"]["bio"] == "hi" and r.json["user"]["image"] == "http://i/x.png"
    assert r.json["user"]["username"] == user["username"]  # partial update keeps others
    r = client.put("/user", {"user": {"bio": "", "image": None}}, token=t)
    assert r.json["user"]["bio"] is None and r.json["user"]["image"] is None
    r = client.put("/user", {"user": {"image": ""}}, token=t)
    assert r.json["user"]["image"] is None
    # same values are not a conflict
    r = client.put("/user", {"user": {"username": user["username"], "email": user["email"]}}, token=t)
    assert r.status == 200
    # change username/email/password
    new = user["username"] + "_n"
    r = client.put("/user", {"user": {"username": new, "email": new + "@example.org", "password": "newpw"}}, token=t)
    assert r.status == 200 and r.json["user"]["username"] == new
    assert client.post("/users/login", {"user": {"email": new + "@example.org", "password": "newpw"}}).status == 200
    assert client.post("/users/login", {"user": {"email": new + "@example.org", "password": user["password"]}}).status == 401
    assert client.get("/profiles/" + new).status == 200


def test_update_user_errors_r7(client, user, make_user):
    other = make_user()
    t = user["token"]
    r = client.put("/user", {"user": {"username": other["username"]}}, token=t)
    assert r.status == 409 and "username" in r.json["errors"]
    r = client.put("/user", {"user": {"email": other["email"].upper()}}, token=t)
    assert r.status == 409 and "email" in r.json["errors"]
    assert client.put("/user", {"user": {"email": "bad"}}, token=t).status == 422
    assert client.put("/user", {"user": {"username": ""}}, token=t).status == 422
    assert client.put("/user", {"user": {"password": ""}}, token=t).status == 422
    assert client.put("/user", {"user": {"bio": 5}}, token=t).status == 422
    assert client.put("/user", {"user": {}}, token=t).status == 422
    assert client.put("/user", {}, token=t).status == 422
    assert client.put("/user", {"user": {"bio": "x"}}).status == 401


def test_response_format_r22(client):
    r = client.get("/nope")
    assert r.status == 404 and "errors" in r.json
    r = client.call("DELETE", "/tags")
    assert r.status == 405 and "errors" in r.json
    r = client.call("OPTIONS", "/articles")
    assert r.status == 204
    assert re.match(r"application/json", client.get("/tags").getheader("Content-Type"))
