from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import csv
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import uuid

from flask import Flask, abort, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "real_estate.sqlite3"
UPLOAD_DIR = BASE_DIR / "uploads"
PROPERTY_TYPES = {"شقة", "فيلا", "بيت", "أرض", "محل"}
PURPOSES = {"sale", "rent"}
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGES = 8
PHONE_PATTERN = re.compile(r"\+?[0-9\s()-]{6,32}")
DEMO_LISTINGS = [
    ("شقة فاخرة بطابق مرتفع بإطلالة مفتوحة", "شقة", "الجلفة", "sale", 14500000, 4, 132, "https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?auto=format&fit=crop&w=900&q=82"),
    ("فيلا مستقلة حديثة مع حديقة خاصة", "فيلا", "عين وسارة", "sale", 28000000, 6, 340, "https://images.unsplash.com/photo-1600607687920-4e2a09cf159d?auto=format&fit=crop&w=900&q=82"),
    ("شقة حديثة مجهزة قرب الخدمات", "شقة", "حاسي بحبح", "rent", 28000, 3, 96, "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?auto=format&fit=crop&w=900&q=82"),
    ("قطعة أرض سكنية بمساحة ممتازة", "أرض", "مسعد", "sale", 4200000, None, 250, "https://images.unsplash.com/photo-1500382017468-9049fed747ef?auto=format&fit=crop&w=900&q=82"),
    ("دار عائلية بواجهة واسعة ومرآب", "بيت", "دار الشيوخ", "sale", 9800000, 5, 210, "https://images.unsplash.com/photo-1568605114967-8130f3a36994?auto=format&fit=crop&w=900&q=82"),
    ("محل تجاري كبير في منطقة حيوية", "محل", "الجلفة", "rent", 65000, None, 78, "https://images.unsplash.com/photo-1600566753086-00f18fb6b3ea?auto=format&fit=crop&w=900&q=82"),
]

app = Flask(__name__)
app.config.update(
    DATABASE=DATABASE,
    UPLOAD_DIR=UPLOAD_DIR,
    ADMIN_KEY=os.environ.get("DARK_ADMIN_KEY", ""),
    SECRET_KEY=os.environ.get("DARK_SESSION_SECRET") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=34 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("DARK_COOKIE_SECURE") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)


@contextmanager
def connect_db():
    connection = sqlite3.connect(app.config["DATABASE"])
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_database(database=None):
    database = Path(database or app.config["DATABASE"])
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                property_type TEXT NOT NULL,
                location TEXT NOT NULL,
                purpose TEXT NOT NULL CHECK (purpose IN ('sale', 'rent')),
                price INTEGER NOT NULL CHECK (price > 0),
                phone TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                rooms INTEGER,
                area INTEGER,
                image TEXT NOT NULL DEFAULT '',
                images TEXT NOT NULL DEFAULT '[]',
                owner_id INTEGER REFERENCES users(id),
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'published')),
                is_demo INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                demo_key TEXT UNIQUE
            )"""
        )
        listing_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(listings)").fetchall()
        }
        if "images" not in listing_columns:
            connection.execute(
                "ALTER TABLE listings ADD COLUMN images TEXT NOT NULL DEFAULT '[]'"
            )
        if "owner_id" not in listing_columns:
            connection.execute("ALTER TABLE listings ADD COLUMN owner_id INTEGER")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                body TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'published')),
                created_at TEXT NOT NULL
            )"""
        )
        for index, listing in enumerate(DEMO_LISTINGS, start=1):
            connection.execute(
                """INSERT OR IGNORE INTO listings
                (title, property_type, location, purpose, price, phone, rooms, area,
                 image, images, status, is_demo, created_at, demo_key)
                VALUES (?, ?, ?, ?, ?, '', ?, ?, ?, '[]', 'published', 1, ?, ?)""",
                (*listing[:5], listing[5], listing[6], listing[7],
                 datetime.now(timezone.utc).isoformat(timespec="seconds"), f"demo-{index}"),
            )
        connection.commit()
    finally:
        connection.close()


def positive_integer(value):
    if isinstance(value, bool):
        raise ValueError
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdecimal():
        parsed = int(value.strip())
    else:
        raise ValueError
    if parsed <= 0:
        raise ValueError
    return parsed


def listing_dict(row):
    result = dict(row)
    result["type"] = result.pop("property_type")
    result["is_demo"] = bool(result["is_demo"])
    try:
        images = json.loads(result.get("images") or "[]")
    except json.JSONDecodeError:
        images = []
    if not isinstance(images, list):
        images = []
    if not images and result.get("image"):
        images = [result["image"]]
    result["images"] = images
    result["image"] = images[0] if images else ""
    result.pop("owner_id", None)
    return result


def csrf_error():
    expected = session.get("csrf_token", "")
    supplied = request.headers.get("X-CSRF-Token", "")
    if not expected or not hmac.compare_digest(expected, supplied):
        return jsonify(error="انتهت صلاحية النموذج. أعد تحميل الصفحة وحاول مجددًا."), 403
    return None


def require_admin():
    configured_key = app.config["ADMIN_KEY"]
    provided_key = request.headers.get("X-Admin-Key", "")
    if not configured_key:
        return jsonify(error="لوحة المراجعة غير مفعلة. يرجى ضبط DARK_ADMIN_KEY."), 503
    if not hmac.compare_digest(configured_key, provided_key):
        return jsonify(error="بيانات الدخول غير صحيحة."), 401
    return None


def save_listing_images(files):
    selected = [file for file in files if file and file.filename]
    if len(selected) > MAX_IMAGES:
        raise ValueError(f"يسمح بتحميل {MAX_IMAGES} صور كحد أقصى.")

    image_data = []
    signatures = (
        (b"\xff\xd8\xff", ".jpg"),
        (b"\x89PNG\r\n\x1a\n", ".png"),
    )
    for uploaded in selected:
        contents = uploaded.stream.read(MAX_IMAGE_BYTES + 1)
        if len(contents) > MAX_IMAGE_BYTES:
            raise ValueError("يجب ألا يتجاوز حجم الصورة الواحدة 4 ميغابايت.")
        extension = next(
            (suffix for signature, suffix in signatures if contents.startswith(signature)),
            None,
        )
        if extension is None and contents.startswith(b"RIFF") and contents[8:12] == b"WEBP":
            extension = ".webp"
        if extension is None:
            raise ValueError("صيغة صورة غير مدعومة. استخدم JPG أو PNG أو WEBP.")
        image_data.append((contents, extension))

    upload_dir = Path(app.config["UPLOAD_DIR"])
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_files = []
    try:
        for contents, extension in image_data:
            filename = f"{uuid.uuid4().hex}{extension}"
            path = upload_dir / filename
            path.write_bytes(contents)
            saved_files.append((path, f"/uploads/{filename}"))
    except OSError:
        for path, _ in saved_files:
            path.unlink(missing_ok=True)
        raise
    return saved_files


def authenticated_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with connect_db() as connection:
        row = connection.execute(
            "SELECT id, name, phone FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


init_database()


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify(error="حجم الصور المرفقة كبير. قلّل حجم الصور ثم أعد المحاولة."), 413


@app.get("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/<path:filename>")
def assets(filename):
    if filename not in {"admin.html", "script.js", "styles.css"}:
        abort(404)
    return send_from_directory(BASE_DIR, filename)


@app.get("/uploads/<path:filename>")
def uploaded_image(filename):
    return send_from_directory(app.config["UPLOAD_DIR"], filename)


@app.get("/api/listings")
def get_listings():
    filters = ["status = 'published'"]
    values = []
    purpose = request.args.get("purpose", "").strip()
    property_type = request.args.get("type", "").strip()
    location = request.args.get("location", "").strip()
    max_price = request.args.get("max_price", "").strip()
    min_rooms = request.args.get("min_rooms", "").strip()
    if purpose in PURPOSES:
        filters.append("purpose = ?")
        values.append(purpose)
    if property_type in PROPERTY_TYPES:
        filters.append("property_type = ?")
        values.append(property_type)
    if location:
        filters.append("location LIKE ?")
        values.append(f"%{location}%")
    if max_price:
        try:
            parsed_price = positive_integer(max_price)
            filters.append("price <= ?")
            values.append(parsed_price)
        except ValueError:
            return jsonify(error="قيمة السعر غير صالحة."), 400
    if min_rooms:
        try:
            parsed_rooms = positive_integer(min_rooms)
            if parsed_rooms > 20:
                raise ValueError
            filters.append("rooms >= ?")
            values.append(parsed_rooms)
        except ValueError:
            return jsonify(error="عدد الغرف غير صالح."), 400

    with connect_db() as connection:
        rows = connection.execute(
            f"SELECT * FROM listings WHERE {' AND '.join(filters)} ORDER BY is_demo ASC, created_at DESC",
            values,
        ).fetchall()
    return jsonify(items=[listing_dict(row) for row in rows])


@app.get("/api/listings/<int:listing_id>/comments")
def get_comments(listing_id):
    with connect_db() as connection:
        listing = connection.execute(
            "SELECT id FROM listings WHERE id = ? AND status = 'published' AND is_demo = 0",
            (listing_id,),
        ).fetchone()
        if not listing:
            return jsonify(error="التعليقات متاحة على الإعلانات المنشورة فقط."), 404
        rows = connection.execute(
            """SELECT comments.id, comments.body, comments.created_at, users.name
            FROM comments JOIN users ON users.id = comments.user_id
            WHERE comments.listing_id = ? AND comments.status = 'published'
            ORDER BY comments.created_at DESC""",
            (listing_id,),
        ).fetchall()
    return jsonify(items=[dict(row) for row in rows])


@app.post("/api/listings/<int:listing_id>/comments")
def create_comment(listing_id):
    csrf = csrf_error()
    if csrf:
        return csrf
    user = authenticated_user()
    if not user:
        return jsonify(error="سجّل الدخول أولًا لإضافة تعليق."), 401
    data = request.get_json(silent=True) or {}
    body = str(data.get("body", "")).strip()
    if len(body) < 2 or len(body) > 2000:
        return jsonify(error="يجب أن يتراوح التعليق بين حرفين و2000 حرف."), 400
    with connect_db() as connection:
        listing = connection.execute(
            "SELECT id FROM listings WHERE id = ? AND status = 'published' AND is_demo = 0",
            (listing_id,),
        ).fetchone()
        if not listing:
            return jsonify(error="التعليقات متاحة على الإعلانات المنشورة فقط."), 404
        cursor = connection.execute(
            """INSERT INTO comments (listing_id, user_id, body, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)""",
            (listing_id, user["id"], body, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
    return jsonify(ok=True, id=cursor.lastrowid, status="pending"), 201


@app.get("/api/auth/me")
def auth_me():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify(user=authenticated_user(), csrf_token=session["csrf_token"])


@app.post("/api/auth/register")
def register():
    csrf = csrf_error()
    if csrf:
        return csrf
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="بيانات التسجيل غير صالحة."), 400
    name = str(data.get("name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    password = data.get("password", "")
    if not name or len(name) > 100:
        return jsonify(error="أدخل اسمًا صحيحًا لا يتجاوز 100 حرف."), 400
    if not PHONE_PATTERN.fullmatch(phone) or sum(char.isdigit() for char in phone) < 6:
        return jsonify(error="رقم الهاتف غير صالح."), 400
    if not isinstance(password, str) or len(password) < 8 or len(password) > 128:
        return jsonify(error="يجب أن تتكون كلمة المرور من 8 إلى 128 حرفًا."), 400
    try:
        with connect_db() as connection:
            cursor = connection.execute(
                "INSERT INTO users (name, phone, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (name, phone, generate_password_hash(password),
                 datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        return jsonify(error="رقم الهاتف مسجل مسبقًا."), 409
    session.clear()
    session.permanent = True
    session["user_id"] = user_id
    session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify(
        user={"id": user_id, "name": name, "phone": phone},
        csrf_token=session["csrf_token"],
    ), 201


@app.post("/api/auth/login")
def login():
    csrf = csrf_error()
    if csrf:
        return csrf
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="بيانات الدخول غير صالحة."), 400
    phone = str(data.get("phone", "")).strip()
    password = data.get("password", "")
    if not isinstance(password, str) or not password or len(password) > 128:
        return jsonify(error="رقم الهاتف أو كلمة المرور غير صحيحة."), 401
    with connect_db() as connection:
        user = connection.execute(
            "SELECT id, name, phone, password_hash FROM users WHERE phone = ?", (phone,)
        ).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify(error="رقم الهاتف أو كلمة المرور غير صحيحة."), 401
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify(
        user={"id": user["id"], "name": user["name"], "phone": user["phone"]},
        csrf_token=session["csrf_token"],
    )


@app.post("/api/auth/logout")
def logout():
    csrf = csrf_error()
    if csrf:
        return csrf
    session.clear()
    session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify(ok=True, csrf_token=session["csrf_token"])


@app.post("/api/inquiry")
def inquiry():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    service = str(data.get("service", "")).strip()
    message = str(data.get("message", "")).strip()

    if not name or not phone:
        return jsonify(error="الاسم ورقم الهاتف مطلوبان"), 400

    with (BASE_DIR / "inquiries.csv").open("a", encoding="utf-8", newline="") as file:
        csv.writer(file).writerow([name, phone, service, message])
    return jsonify(ok=True)


@app.post("/api/listings")
def create_listing():
    if request.mimetype == "application/json":
        data = request.get_json(silent=True)
        files = []
    else:
        data = request.form
        files = request.files.getlist("images")
    if not data:
        return jsonify(error="بيانات الإعلان غير صالحة."), 400

    title = str(data.get("title", "")).strip()
    location = str(data.get("location", "")).strip()
    phone = str(data.get("phone", "")).strip()
    property_type = str(data.get("type", "")).strip()
    purpose = str(data.get("purpose", "")).strip()
    description = str(data.get("description", "")).strip()
    accepted = data.get("accept_terms") in (True, "true", "on", "1")
    if not accepted:
        return jsonify(error="يرجى تأكيد صحة معلومات العقار قبل الإرسال."), 400
    if not title or not location or not phone:
        return jsonify(error="العنوان والمنطقة ورقم الهاتف مطلوبة."), 400
    if len(title) > 160 or len(location) > 100 or len(phone) > 32 or len(description) > 5000:
        return jsonify(error="تجاوز أحد الحقول الحد المسموح."), 400
    if not PHONE_PATTERN.fullmatch(phone) or sum(char.isdigit() for char in phone) < 6:
        return jsonify(error="رقم الهاتف غير صالح."), 400
    if property_type not in PROPERTY_TYPES or purpose not in PURPOSES:
        return jsonify(error="نوع العقار أو الغرض غير صالح."), 400
    try:
        price = positive_integer(data.get("price", 0))
        area = positive_integer(data["area"]) if data.get("area") not in (None, "") else None
        rooms = positive_integer(data["rooms"]) if data.get("rooms") not in (None, "") else None
        if price > 100_000_000_000 or (area is not None and area > 10_000_000) or (rooms is not None and rooms > 200):
            raise ValueError
    except (TypeError, ValueError):
        return jsonify(error="السعر والمساحة وعدد الغرف يجب أن تكون أرقامًا موجبة."), 400

    try:
        saved_images = save_listing_images(files)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    image_urls = [url for _, url in saved_images]
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with connect_db() as connection:
            cursor = connection.execute(
                """INSERT INTO listings
                (title, property_type, location, purpose, price, phone, description,
                 rooms, area, image, images, owner_id, status, is_demo, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?)""",
                (title, property_type, location, purpose, price, phone, description,
                 rooms, area, image_urls[0] if image_urls else "",
                 json.dumps(image_urls), session.get("user_id"), created_at),
            )
            listing_id = cursor.lastrowid
    except sqlite3.Error:
        for path, _ in saved_images:
            path.unlink(missing_ok=True)
        raise
    return jsonify(ok=True, id=listing_id, status="pending"), 201


@app.get("/api/admin/listings")
def pending_listings():
    auth_error = require_admin()
    if auth_error:
        return auth_error
    with connect_db() as connection:
        rows = connection.execute(
            "SELECT * FROM listings WHERE status = 'pending' ORDER BY created_at ASC"
        ).fetchall()
    return jsonify(items=[listing_dict(row) for row in rows])


@app.post("/api/admin/listings/<int:listing_id>/approve")
def approve_listing(listing_id):
    auth_error = require_admin()
    if auth_error:
        return auth_error
    with connect_db() as connection:
        cursor = connection.execute(
            "UPDATE listings SET status = 'published' WHERE id = ? AND status = 'pending'",
            (listing_id,),
        )
    if cursor.rowcount == 0:
        return jsonify(error="الإعلان غير موجود أو تمت مراجعته مسبقًا."), 404
    return jsonify(ok=True)


@app.get("/api/admin/comments")
def pending_comments():
    auth_error = require_admin()
    if auth_error:
        return auth_error
    with connect_db() as connection:
        rows = connection.execute(
            """SELECT comments.id, comments.listing_id, comments.body, comments.created_at,
            users.name AS author, listings.title AS listing_title
            FROM comments JOIN users ON users.id = comments.user_id
            JOIN listings ON listings.id = comments.listing_id
            WHERE comments.status = 'pending' ORDER BY comments.created_at ASC"""
        ).fetchall()
    return jsonify(items=[dict(row) for row in rows])


@app.post("/api/admin/comments/<int:comment_id>/approve")
def approve_comment(comment_id):
    auth_error = require_admin()
    if auth_error:
        return auth_error
    with connect_db() as connection:
        cursor = connection.execute(
            "UPDATE comments SET status = 'published' WHERE id = ? AND status = 'pending'",
            (comment_id,),
        )
    if cursor.rowcount == 0:
        return jsonify(error="التعليق غير موجود أو تمت مراجعته مسبقًا."), 404
    return jsonify(ok=True)


@app.delete("/api/admin/comments/<int:comment_id>")
def reject_comment(comment_id):
    auth_error = require_admin()
    if auth_error:
        return auth_error
    with connect_db() as connection:
        cursor = connection.execute(
            "DELETE FROM comments WHERE id = ? AND status = 'pending'", (comment_id,)
        )
    if cursor.rowcount == 0:
        return jsonify(error="التعليق غير موجود أو تمت مراجعته مسبقًا."), 404
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
