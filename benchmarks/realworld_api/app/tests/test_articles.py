"""Articles, feed, filters, tags, favorites, comments: R10-R20, R23."""
import re
import time

TS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


def test_create_article_r10_r20(client, user):
    r = client.post("/articles", {"article": {"title": "My First Post!", "description": "d", "body": "b",
                                              "tagList": ["z", "a", "m"]}}, token=user["token"])
    assert r.status == 201
    a = r.json["article"]
    assert a["slug"].startswith("my-first-post")
    assert a["title"] == "My First Post!" and a["body"] == "b" and a["description"] == "d"
    assert a["tagList"] == ["z", "a", "m"]  # stored order R17
    assert a["favorited"] is False and a["favoritesCount"] == 0
    assert a["author"] == {"username": user["username"], "bio": None, "image": None, "following": False}
    assert TS.match(a["createdAt"]) and TS.match(a["updatedAt"])


def test_create_article_defaults_and_errors_r10(client, user):
    r = client.post("/articles", {"article": {"title": "No tags", "description": "d", "body": "b"}}, token=user["token"])
    assert r.json["article"]["tagList"] == []
    t = user["token"]
    for f in ("title", "description", "body"):
        body = {"title": "t", "description": "d", "body": "b"}
        del body[f]
        r = client.post("/articles", {"article": body}, token=t)
        assert r.status == 422 and r.json["errors"][f] == ["can't be blank"]
        body[f] = ""
        assert client.post("/articles", {"article": body}, token=t).status == 422
    bad = {"title": "t", "description": "d", "body": "b", "tagList": "x"}
    assert client.post("/articles", {"article": bad}, token=t).status == 422
    bad["tagList"] = [1]
    assert client.post("/articles", {"article": bad}, token=t).status == 422
    assert client.post("/articles", {}, token=t).status == 422
    assert client.post("/articles", {"article": {"title": "t", "description": "d", "body": "b"}}).status == 401


def test_slug_unique_r11(client, user, make_article):
    a1 = make_article(user, "Same Title Slug")
    a2 = make_article(user, "Same Title Slug")
    a3 = make_article(user, "Same Title Slug")
    assert len({a1["slug"], a2["slug"], a3["slug"]}) == 3
    assert a2["slug"] == a1["slug"] + "-2" and a3["slug"] == a1["slug"] + "-3"
    assert make_article(user, "!!!")["slug"].startswith("article")


def test_tag_dedup_r17(client, user, make_article):
    a = make_article(user, "dups", ["x", "y", "x", "z", "y"])
    assert a["tagList"] == ["x", "y", "z"]


def test_get_article_r12(client, user, make_user, make_article):
    a = make_article(user, "Gettable")
    r = client.get("/articles/" + a["slug"])
    assert r.status == 200 and r.json["article"] == a
    other = make_user()
    client.post("/profiles/%s/follow" % user["username"], token=other["token"])
    r = client.get("/articles/" + a["slug"], token=other["token"])
    assert r.json["article"]["author"]["following"] is True
    r = client.get("/articles/does-not-exist")
    assert r.status == 404 and r.json == {"errors": {"article": ["not found"]}}


def test_update_article_r13(client, user, make_user, make_article):
    a = make_article(user, "Original Title", ["t1"])
    t = user["token"]
    r = client.put("/articles/" + a["slug"], {"article": {"body": "new body"}}, token=t)
    assert r.status == 200
    b = r.json["article"]
    assert b["body"] == "new body" and b["slug"] == a["slug"] and b["title"] == a["title"] and b["tagList"] == ["t1"]
    assert b["createdAt"] == a["createdAt"]
    time.sleep(0.01)
    r = client.put("/articles/" + a["slug"], {"article": {"title": "Brand New", "tagList": ["q", "p"],
                                                          "description": "nd"}}, token=t)
    c = r.json["article"]
    assert c["slug"].startswith("brand-new") and c["tagList"] == ["q", "p"] and c["description"] == "nd"
    assert c["updatedAt"] >= b["updatedAt"]
    assert client.get("/articles/" + a["slug"]).status == 404
    assert client.get("/articles/" + c["slug"]).status == 200
    # same title keeps slug; slug collision with another article
    other_a = make_article(user, "Collide Me")
    r = client.put("/articles/" + c["slug"], {"article": {"title": "Collide Me"}}, token=t)
    assert r.json["article"]["slug"] == other_a["slug"] + "-2"
    r = client.put("/articles/" + other_a["slug"], {"article": {"title": "Collide Me"}}, token=t)
    assert r.json["article"]["slug"] == other_a["slug"]
    # empty tag list clears
    assert client.put("/articles/" + other_a["slug"], {"article": {"tagList": []}}, token=t).json["article"]["tagList"] == []


def test_update_article_errors_r13_r23(client, user, make_user, make_article):
    a = make_article(user, "Guarded")
    other = make_user()
    p = "/articles/" + a["slug"]
    r = client.put(p, {"article": {"body": "x"}}, token=other["token"])
    assert r.status == 403 and r.json == {"errors": {"article": ["forbidden"]}}
    assert client.put(p, {"article": {"body": "x"}}).status == 401
    assert client.put("/articles/nope", {"article": {"body": "x"}}, token=user["token"]).status == 404
    assert client.put(p, {"article": {"title": ""}}, token=user["token"]).status == 422
    assert client.put(p, {"article": {}}, token=user["token"]).status == 422
    assert client.put(p, {"article": {"tagList": "no"}}, token=user["token"]).status == 422
    # 403 beats 422 for non-author
    assert client.put(p, {"article": {"title": ""}}, token=other["token"]).status == 403


def test_delete_article_r14(client, user, make_user, make_article):
    a = make_article(user, "To Delete", ["deltag_unique"])
    other = make_user()
    p = "/articles/" + a["slug"]
    client.post(p + "/favorite", token=other["token"])
    client.post(p + "/comments", {"comment": {"body": "c"}}, token=other["token"])
    assert client.delete(p).status == 401
    assert client.delete(p, token=other["token"]).status == 403
    r = client.delete(p, token=user["token"])
    assert r.status == 204 and r.text == ""
    assert client.get(p).status == 404
    assert client.delete(p, token=user["token"]).status == 404
    assert "deltag_unique" not in client.get("/tags").json["tags"]
    assert client.get("/articles?favorited=" + other["username"]).json["articlesCount"] == 0


def test_list_and_filters_r15(client, make_user, make_article):
    a, b = make_user(), make_user()
    tag = "tg" + a["username"]
    a1 = make_article(a, "L one", [tag, "common"])
    a2 = make_article(a, "L two", ["common"])
    b1 = make_article(b, "L three", [tag])
    r = client.get("/articles?tag=" + tag)
    assert [x["slug"] for x in r.json["articles"]] == [b1["slug"], a1["slug"]]  # newest first
    assert r.json["articlesCount"] == 2
    assert all("body" not in x for x in r.json["articles"])
    r = client.get("/articles?author=" + a["username"])
    assert [x["slug"] for x in r.json["articles"]] == [a2["slug"], a1["slug"]]
    r = client.get("/articles?author=%s&tag=%s" % (a["username"], tag))
    assert [x["slug"] for x in r.json["articles"]] == [a1["slug"]]
    client.post("/articles/%s/favorite" % a2["slug"], token=b["token"])
    r = client.get("/articles?favorited=" + b["username"])
    assert [x["slug"] for x in r.json["articles"]] == [a2["slug"]]
    assert r.json["articles"][0]["favoritesCount"] == 1
    assert r.json["articles"][0]["favorited"] is False
    assert client.get("/articles?favorited=" + b["username"], token=b["token"]).json["articles"][0]["favorited"] is True
    for q in ("tag=nonexistent_zz", "author=ghost_zz", "favorited=ghost_zz"):
        r = client.get("/articles?" + q)
        assert r.status == 200 and r.json == {"articles": [], "articlesCount": 0}


def test_pagination_r15(client, make_user, make_article):
    u = make_user()
    slugs = [make_article(u, "P%d" % i)["slug"] for i in range(5)]
    base = "/articles?author=" + u["username"]
    r = client.get(base)
    assert [x["slug"] for x in r.json["articles"]] == slugs[::-1] and r.json["articlesCount"] == 5
    r = client.get(base + "&limit=2&offset=1")
    assert [x["slug"] for x in r.json["articles"]] == [slugs[3], slugs[2]]
    assert r.json["articlesCount"] == 5
    assert client.get(base + "&offset=10").json == {"articles": [], "articlesCount": 5}
    for q in ("limit=0", "limit=x", "offset=-1", "offset=abc", "limit=-3"):
        r = client.get(base + "&" + q)
        assert r.status == 422 and "errors" in r.json


def test_default_limit_r15(client, make_user, make_article):
    u = make_user()
    for i in range(22):
        make_article(u, "D%d" % i)
    r = client.get("/articles?author=" + u["username"])
    assert len(r.json["articles"]) == 20 and r.json["articlesCount"] == 22


def test_feed_r16(client, make_user, make_article):
    me, f1, f2, stranger = make_user(), make_user(), make_user(), make_user()
    make_article(stranger, "not followed")
    x = make_article(f1, "feed x")
    y = make_article(f2, "feed y")
    for f in (f1, f2):
        client.post("/profiles/%s/follow" % f["username"], token=me["token"])
    assert client.get("/articles/feed").status == 401
    r = client.get("/articles/feed", token=me["token"])
    assert [a["slug"] for a in r.json["articles"]] == [y["slug"], x["slug"]]
    assert r.json["articlesCount"] == 2 and all("body" not in a for a in r.json["articles"])
    assert all(a["author"]["following"] for a in r.json["articles"])
    r = client.get("/articles/feed?limit=1&offset=1", token=me["token"])
    assert [a["slug"] for a in r.json["articles"]] == [x["slug"]] and r.json["articlesCount"] == 2
    assert client.get("/articles/feed?limit=0", token=me["token"]).status == 422
    assert client.get("/articles/feed", token=stranger["token"]).json == {"articles": [], "articlesCount": 0}


def test_tags_r17(client, make_user, make_article):
    u = make_user()
    n = u["username"]
    make_article(u, "tg1", ["first" + n, "second" + n])
    make_article(u, "tg2", ["second" + n, "third" + n])
    r = client.get("/tags")
    assert r.status == 200
    tags = r.json["tags"]
    mine = [t for t in tags if t.endswith(n)]
    assert mine == ["first" + n, "second" + n, "third" + n]
    assert len(tags) == len(set(tags))


def test_favorites_r19(client, user, make_user, make_article):
    a = make_article(user, "Fav me")
    other = make_user()
    p = "/articles/%s/favorite" % a["slug"]
    r = client.post(p, token=other["token"])
    assert r.status == 200 and r.json["article"]["favorited"] is True and r.json["article"]["favoritesCount"] == 1
    assert client.post(p, token=other["token"]).json["article"]["favoritesCount"] == 1  # idempotent
    assert client.post(p, token=user["token"]).json["article"]["favoritesCount"] == 2
    assert client.get("/articles/" + a["slug"]).json["article"]["favorited"] is False
    r = client.delete(p, token=other["token"])
    assert r.status == 200 and r.json["article"]["favorited"] is False and r.json["article"]["favoritesCount"] == 1
    assert client.delete(p, token=other["token"]).json["article"]["favoritesCount"] == 1
    assert client.post(p).status == 401 and client.delete(p).status == 401
    assert client.post("/articles/zzz/favorite", token=user["token"]).status == 404
    assert client.delete("/articles/zzz/favorite", token=user["token"]).status == 404


def test_comments_r18(client, user, make_user, make_article):
    a = make_article(user, "Commented")
    other = make_user()
    p = "/articles/%s/comments" % a["slug"]
    assert client.get(p).json == {"comments": []}
    r = client.post(p, {"comment": {"body": "first"}}, token=other["token"])
    assert r.status == 201
    c1 = r.json["comment"]
    assert set(c1) == {"id", "createdAt", "updatedAt", "body", "author"} and isinstance(c1["id"], int)
    assert TS.match(c1["createdAt"]) and c1["body"] == "first"
    assert c1["author"]["username"] == other["username"]
    c2 = client.post(p, {"comment": {"body": "second"}}, token=user["token"]).json["comment"]
    client.post("/profiles/%s/follow" % other["username"], token=user["token"])
    r = client.get(p, token=user["token"])
    assert [c["body"] for c in r.json["comments"]] == ["first", "second"]
    assert r.json["comments"][0]["author"]["following"] is True
    assert r.json["comments"][1]["author"]["following"] is False
    assert client.get(p).status == 200
    assert client.get("/articles/zzz/comments").status == 404
    assert client.get(p, token="bad").status == 401


def test_comment_errors_r18(client, user, make_article):
    a = make_article(user, "Comment errs")
    p = "/articles/%s/comments" % a["slug"]
    assert client.post(p, {"comment": {"body": "x"}}).status == 401
    assert client.post("/articles/zzz/comments", {"comment": {"body": "x"}}, token=user["token"]).status == 404
    for body in ({"comment": {"body": ""}}, {"comment": {}}, {}, {"comment": {"body": 3}}):
        r = client.post(p, body, token=user["token"])
        assert r.status == 422 and "errors" in r.json


def test_delete_comment_r18(client, user, make_user, make_article):
    a = make_article(user, "Del comments")
    b = make_article(user, "Other article")
    other = make_user()
    p = "/articles/%s/comments" % a["slug"]
    c = client.post(p, {"comment": {"body": "mine"}}, token=other["token"]).json["comment"]
    d = "%s/%d" % (p, c["id"])
    assert client.delete(d).status == 401
    r = client.delete(d, token=user["token"])
    assert r.status == 403 and r.json == {"errors": {"comment": ["forbidden"]}}
    assert client.delete("/articles/%s/comments/%d" % (b["slug"], c["id"]), token=other["token"]).status == 404
    assert client.delete("/articles/zzz/comments/%d" % c["id"], token=other["token"]).status == 404
    assert client.delete(p + "/999999", token=other["token"]).status == 404
    assert client.delete(p + "/abc", token=other["token"]).status == 422
    r = client.delete(d, token=other["token"])
    assert r.status == 204 and r.text == ""
    assert client.get(p).json == {"comments": []}
    assert client.delete(d, token=other["token"]).status == 404


def test_slug_feed_reserved_r11(client, user, make_article):
    """An article titled 'Feed' must stay reachable (GET /articles/feed is the feed route)."""
    a = make_article(user, "Feed")
    assert a["slug"] != "feed"
    assert client.get("/articles/" + a["slug"]).json["article"]["title"] == "Feed"
