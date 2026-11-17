"""Profiles: R8, R9."""


def test_get_profile_r8(client, user):
    r = client.get("/profiles/" + user["username"])
    assert r.status == 200
    assert r.json == {"profile": {"username": user["username"], "bio": None, "image": None, "following": False}}
    r = client.get("/profiles/no_such_user_zz")
    assert r.status == 404 and r.json == {"errors": {"profile": ["not found"]}}
    assert client.get("/profiles/" + user["username"], token="junk").status == 401


def test_follow_unfollow_r9(client, make_user):
    a, b = make_user(), make_user()
    p = "/profiles/%s/follow" % b["username"]
    r = client.post(p, token=a["token"])
    assert r.status == 200 and r.json["profile"]["following"] is True
    assert client.post(p, token=a["token"]).json["profile"]["following"] is True  # idempotent
    assert client.get("/profiles/" + b["username"], token=a["token"]).json["profile"]["following"] is True
    assert client.get("/profiles/" + b["username"], token=b["token"]).json["profile"]["following"] is False
    assert client.get("/profiles/" + b["username"]).json["profile"]["following"] is False
    r = client.delete(p, token=a["token"])
    assert r.status == 200 and r.json["profile"]["following"] is False
    assert client.delete(p, token=a["token"]).status == 200


def test_follow_errors_r9(client, user):
    assert client.post("/profiles/%s/follow" % user["username"]).status == 401
    assert client.delete("/profiles/%s/follow" % user["username"]).status == 401
    assert client.post("/profiles/ghost_zz/follow", token=user["token"]).status == 404
    assert client.delete("/profiles/ghost_zz/follow", token=user["token"]).status == 404
