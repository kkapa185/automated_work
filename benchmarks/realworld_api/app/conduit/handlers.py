"""Endpoint handlers. Each takes a Request (db, user, query, body) and returns (status, payload)."""
from . import auth
from .util import ApiError, EMAIL_RE, blank, now_iso, unique_slug


def err(status, field, msg):
    return ApiError(status, {field: [msg]})


# ---------------------------------------------------------------- serializers
def user_json(u):
    return {"user": {"email": u["email"], "token": auth.make_token(u["id"], u["username"]),
                     "username": u["username"], "bio": u["bio"], "image": u["image"]}}


def following(db, viewer, author_id):
    if viewer is None:
        return False
    return db.execute("SELECT 1 FROM follows WHERE follower_id=? AND followed_id=?",
                      (viewer["id"], author_id)).fetchone() is not None


def profile_obj(db, viewer, u):
    return {"username": u["username"], "bio": u["bio"], "image": u["image"],
            "following": following(db, viewer, u["id"])}


def article_obj(db, viewer, a, with_body=True):
    tags = [r["tag"] for r in db.execute(
        "SELECT tag FROM article_tags WHERE article_id=? ORDER BY id", (a["id"],))]
    count = db.execute("SELECT COUNT(*) c FROM favorites WHERE article_id=?", (a["id"],)).fetchone()["c"]
    fav = viewer is not None and db.execute(
        "SELECT 1 FROM favorites WHERE user_id=? AND article_id=?", (viewer["id"], a["id"])).fetchone() is not None
    author = db.execute("SELECT * FROM users WHERE id=?", (a["author_id"],)).fetchone()
    o = {"slug": a["slug"], "title": a["title"], "description": a["description"]}
    if with_body:
        o["body"] = a["body"]
    o.update({"tagList": tags, "createdAt": a["created_at"], "updatedAt": a["updated_at"],
              "favorited": fav, "favoritesCount": count, "author": profile_obj(db, viewer, author)})
    return o


def comment_obj(db, viewer, c):
    author = db.execute("SELECT * FROM users WHERE id=?", (c["author_id"],)).fetchone()
    return {"id": c["id"], "createdAt": c["created_at"], "updatedAt": c["updated_at"],
            "body": c["body"], "author": profile_obj(db, viewer, author)}


# ---------------------------------------------------------------- helpers
def get_article(req, slug):
    a = req.db.execute("SELECT * FROM articles WHERE slug=?", (slug,)).fetchone()
    if a is None:
        raise err(404, "article", "not found")
    return a


def wrapped(req, key):
    b = req.body()
    v = b.get(key) if isinstance(b, dict) else None
    if not isinstance(v, dict):
        raise err(422, key, "can't be blank")
    return v


def check_text(errors, obj, field, required):
    if field in obj:
        if blank(obj[field]):
            errors.setdefault(field, []).append("can't be blank")
    elif required:
        errors.setdefault(field, []).append("can't be blank")


def check_email(errors, v):
    if blank(v):
        errors.setdefault("email", []).append("can't be blank")
    elif not EMAIL_RE.match(v.strip()):
        errors.setdefault("email", []).append("is invalid")


def check_nullable(errors, obj, field):
    if field in obj and obj[field] is not None and not isinstance(obj[field], str):
        errors.setdefault(field, []).append("must be a string or null")


def norm_nullable(v):
    return None if v is None or v == "" else v


def check_tags(errors, obj, required=False):
    if "tagList" not in obj:
        return None
    t = obj["tagList"]
    if not isinstance(t, list) or any(not isinstance(x, str) for x in t):
        errors.setdefault("tagList", []).append("must be an array of strings")
        return None
    out = []
    for x in t:
        if x not in out:
            out.append(x)
    return out


def page_params(req):
    out = []
    errors = {}
    for name, default, lo in (("limit", 20, 1), ("offset", 0, 0)):
        raw = req.query.get(name)
        if raw is None:
            out.append(default)
            continue
        try:
            n = int(raw)
            if n < lo:
                raise ValueError
            out.append(n)
        except ValueError:
            errors[name] = ["must be an integer >= %d" % lo]
            out.append(default)
    if errors:
        raise ApiError(422, errors)
    return out


# ---------------------------------------------------------------- users
def register(req):
    u = wrapped(req, "user")
    errors = {}
    check_text(errors, u, "username", True)
    check_email(errors, u.get("email"))
    check_text(errors, u, "password", True)
    if errors:
        raise ApiError(422, errors)
    username, email = u["username"].strip(), u["email"].strip()
    conflicts = {}
    if req.db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        conflicts["username"] = ["has already been taken"]
    if req.db.execute("SELECT 1 FROM users WHERE lower(email)=lower(?)", (email,)).fetchone():
        conflicts["email"] = ["has already been taken"]
    if conflicts:
        raise ApiError(409, conflicts)
    cur = req.db.execute("INSERT INTO users(username,email,password_hash) VALUES(?,?,?)",
                         (username, email, auth.hash_password(u["password"])))
    row = req.db.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
    return 201, user_json(row)


def login(req):
    u = wrapped(req, "user")
    errors = {}
    check_email(errors, u.get("email"))
    check_text(errors, u, "password", True)
    if errors:
        raise ApiError(422, errors)
    row = req.db.execute("SELECT * FROM users WHERE lower(email)=lower(?)", (u["email"].strip(),)).fetchone()
    if row is None or not auth.check_password(u["password"], row["password_hash"]):
        raise err(401, "email or password", "is invalid")
    return 200, user_json(row)


def current_user(req):
    return 200, user_json(req.user)


def update_user(req):
    u = wrapped(req, "user")
    fields = [f for f in ("email", "username", "password", "bio", "image") if f in u]
    if not fields:
        raise err(422, "user", "at least one field is required")
    errors = {}
    if "email" in u:
        check_email(errors, u["email"])
    check_text(errors, u, "username", False)
    check_text(errors, u, "password", False)
    check_nullable(errors, u, "bio")
    check_nullable(errors, u, "image")
    if errors:
        raise ApiError(422, errors)
    me = req.user
    username = u["username"].strip() if "username" in u else me["username"]
    email = u["email"].strip() if "email" in u else me["email"]
    conflicts = {}
    if req.db.execute("SELECT 1 FROM users WHERE username=? AND id<>?", (username, me["id"])).fetchone():
        conflicts["username"] = ["has already been taken"]
    if req.db.execute("SELECT 1 FROM users WHERE lower(email)=lower(?) AND id<>?", (email, me["id"])).fetchone():
        conflicts["email"] = ["has already been taken"]
    if conflicts:
        raise ApiError(409, conflicts)
    pw = auth.hash_password(u["password"]) if "password" in u else me["password_hash"]
    bio = norm_nullable(u["bio"]) if "bio" in u else me["bio"]
    image = norm_nullable(u["image"]) if "image" in u else me["image"]
    req.db.execute("UPDATE users SET username=?,email=?,password_hash=?,bio=?,image=? WHERE id=?",
                   (username, email, pw, bio, image, me["id"]))
    return 200, user_json(req.db.execute("SELECT * FROM users WHERE id=?", (me["id"],)).fetchone())


# ---------------------------------------------------------------- profiles
def get_profile_user(req, username):
    u = req.db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if u is None:
        raise err(404, "profile", "not found")
    return u


def get_profile(req, username):
    return 200, {"profile": profile_obj(req.db, req.user, get_profile_user(req, username))}


def follow(req, username):
    u = get_profile_user(req, username)
    req.db.execute("INSERT OR IGNORE INTO follows VALUES(?,?)", (req.user["id"], u["id"]))
    return 200, {"profile": profile_obj(req.db, req.user, u)}


def unfollow(req, username):
    u = get_profile_user(req, username)
    req.db.execute("DELETE FROM follows WHERE follower_id=? AND followed_id=?", (req.user["id"], u["id"]))
    return 200, {"profile": profile_obj(req.db, req.user, u)}


# ---------------------------------------------------------------- articles
def _list(req, where, params):
    limit, offset = page_params(req)
    base = "FROM articles a WHERE " + where
    total = req.db.execute("SELECT COUNT(*) c " + base, params).fetchone()["c"]
    rows = req.db.execute("SELECT a.* " + base + " ORDER BY a.created_at DESC, a.id DESC LIMIT ? OFFSET ?",
                          params + [limit, offset]).fetchall()
    return 200, {"articles": [article_obj(req.db, req.user, r, False) for r in rows],
                 "articlesCount": total}


def list_articles(req):
    page_params(req)
    where, params = ["1=1"], []
    q = req.query
    if "tag" in q:
        where.append("EXISTS(SELECT 1 FROM article_tags t WHERE t.article_id=a.id AND t.tag=?)")
        params.append(q["tag"])
    if "author" in q:
        where.append("a.author_id IN (SELECT id FROM users WHERE username=?)")
        params.append(q["author"])
    if "favorited" in q:
        where.append("a.id IN (SELECT f.article_id FROM favorites f JOIN users u ON u.id=f.user_id "
                     "WHERE u.username=?)")
        params.append(q["favorited"])
    return _list(req, " AND ".join(where), params)


def feed(req):
    return _list(req, "a.author_id IN (SELECT followed_id FROM follows WHERE follower_id=?)", [req.user["id"]])


def add_tags(db, aid, tags):
    for t in tags:
        db.execute("INSERT INTO article_tags(article_id,tag) VALUES(?,?)", (aid, t))


def create_article(req):
    a = wrapped(req, "article")
    errors = {}
    for f in ("title", "description", "body"):
        check_text(errors, a, f, True)
    tags = check_tags(errors, a) or []
    if errors:
        raise ApiError(422, errors)
    now = now_iso()
    slug = unique_slug(req.db, a["title"])
    cur = req.db.execute(
        "INSERT INTO articles(slug,title,description,body,author_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
        (slug, a["title"], a["description"], a["body"], req.user["id"], now, now))
    add_tags(req.db, cur.lastrowid, tags)
    row = req.db.execute("SELECT * FROM articles WHERE id=?", (cur.lastrowid,)).fetchone()
    return 201, {"article": article_obj(req.db, req.user, row)}


def read_article(req, slug):
    return 200, {"article": article_obj(req.db, req.user, get_article(req, slug))}


def update_article(req, slug):
    art = get_article(req, slug)
    if art["author_id"] != req.user["id"]:
        raise err(403, "article", "forbidden")
    a = wrapped(req, "article")
    fields = [f for f in ("title", "description", "body", "tagList") if f in a]
    if not fields:
        raise err(422, "article", "at least one field is required")
    errors = {}
    for f in ("title", "description", "body"):
        check_text(errors, a, f, False)
    tags = check_tags(errors, a)
    if errors:
        raise ApiError(422, errors)
    title = a.get("title", art["title"])
    new_slug = art["slug"] if title == art["title"] else unique_slug(req.db, title, art["id"])
    req.db.execute("UPDATE articles SET slug=?,title=?,description=?,body=?,updated_at=? WHERE id=?",
                   (new_slug, title, a.get("description", art["description"]),
                    a.get("body", art["body"]), now_iso(), art["id"]))
    if tags is not None:
        req.db.execute("DELETE FROM article_tags WHERE article_id=?", (art["id"],))
        add_tags(req.db, art["id"], tags)
    row = req.db.execute("SELECT * FROM articles WHERE id=?", (art["id"],)).fetchone()
    return 200, {"article": article_obj(req.db, req.user, row)}


def delete_article(req, slug):
    art = get_article(req, slug)
    if art["author_id"] != req.user["id"]:
        raise err(403, "article", "forbidden")
    req.db.execute("DELETE FROM articles WHERE id=?", (art["id"],))
    return 204, None


def tags(req):
    rows = req.db.execute("SELECT tag FROM article_tags GROUP BY tag ORDER BY MIN(id)").fetchall()
    return 200, {"tags": [r["tag"] for r in rows]}


# ---------------------------------------------------------------- favorites
def favorite(req, slug):
    art = get_article(req, slug)
    req.db.execute("INSERT OR IGNORE INTO favorites VALUES(?,?)", (req.user["id"], art["id"]))
    return 200, {"article": article_obj(req.db, req.user, art)}


def unfavorite(req, slug):
    art = get_article(req, slug)
    req.db.execute("DELETE FROM favorites WHERE user_id=? AND article_id=?", (req.user["id"], art["id"]))
    return 200, {"article": article_obj(req.db, req.user, art)}


# ---------------------------------------------------------------- comments
def list_comments(req, slug):
    art = get_article(req, slug)
    rows = req.db.execute("SELECT * FROM comments WHERE article_id=? ORDER BY id", (art["id"],)).fetchall()
    return 200, {"comments": [comment_obj(req.db, req.user, c) for c in rows]}


def add_comment(req, slug):
    art = get_article(req, slug)
    c = wrapped(req, "comment")
    errors = {}
    check_text(errors, c, "body", True)
    if errors:
        raise ApiError(422, errors)
    now = now_iso()
    cur = req.db.execute("INSERT INTO comments(article_id,author_id,body,created_at,updated_at) VALUES(?,?,?,?,?)",
                         (art["id"], req.user["id"], c["body"], now, now))
    row = req.db.execute("SELECT * FROM comments WHERE id=?", (cur.lastrowid,)).fetchone()
    return 201, {"comment": comment_obj(req.db, req.user, row)}


def delete_comment(req, slug, id):
    art = get_article(req, slug)
    try:
        cid = int(id)
    except ValueError:
        raise err(422, "id", "must be an integer")
    c = req.db.execute("SELECT * FROM comments WHERE id=? AND article_id=?", (cid, art["id"])).fetchone()
    if c is None:
        raise err(404, "comment", "not found")
    if c["author_id"] != req.user["id"]:
        raise err(403, "comment", "forbidden")
    req.db.execute("DELETE FROM comments WHERE id=?", (cid,))
    return 204, None
