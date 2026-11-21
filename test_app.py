from io import BytesIO
import sqlite3
import tempfile
import unittest
from pathlib import Path

from oussama import app, init_database


class ListingApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_database = app.config["DATABASE"]
        self.original_admin_key = app.config["ADMIN_KEY"]
        self.original_secret_key = app.config["SECRET_KEY"]
        self.original_upload_dir = app.config["UPLOAD_DIR"]
        app.config["DATABASE"] = Path(self.temporary_directory.name) / "test.sqlite3"
        app.config["ADMIN_KEY"] = "test-admin-key"
        app.config["SECRET_KEY"] = "test-session-secret"
        app.config["UPLOAD_DIR"] = Path(self.temporary_directory.name) / "uploads"
        init_database()
        self.client = app.test_client()

    def tearDown(self):
        app.config["DATABASE"] = self.original_database
        app.config["ADMIN_KEY"] = self.original_admin_key
        app.config["SECRET_KEY"] = self.original_secret_key
        app.config["UPLOAD_DIR"] = self.original_upload_dir
        self.temporary_directory.cleanup()

    def test_public_feed_contains_only_published_seed_listings(self):
        response = self.client.get("/api/listings")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["items"]), 6)
        self.assertTrue(all(item["is_demo"] for item in response.json["items"]))

    def test_private_project_files_are_not_served_as_static_assets(self):
        for path in ("/oussama.py", "/inquiries.csv", "/real_estate.sqlite3", "/test_app.py"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_new_listing_is_pending_until_admin_approves_it(self):
        listing = {
            "title": "شقة اختبار",
            "location": "الجلفة",
            "phone": "0550 00 00 00",
            "type": "شقة",
            "purpose": "sale",
            "price": "12000000",
            "area": "120",
            "rooms": "4",
            "accept_terms": True,
        }
        created = self.client.post("/api/listings", json=listing)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json["status"], "pending")
        self.assertEqual(len(self.client.get("/api/listings").json["items"]), 6)

        headers = {"X-Admin-Key": "test-admin-key"}
        approved = self.client.post(
            f"/api/admin/listings/{created.json['id']}/approve", headers=headers
        )
        self.assertEqual(approved.status_code, 200)
        public_items = self.client.get("/api/listings").json["items"]
        self.assertEqual(len(public_items), 7)
        self.assertFalse(public_items[0]["is_demo"])
        self.assertEqual(public_items[0]["title"], listing["title"])

    def test_invalid_listing_is_rejected(self):
        response = self.client.post(
            "/api/listings",
            json={"title": "إعلان", "location": "الجلفة", "phone": "0550000000",
                  "type": "شقة", "purpose": "sale", "price": "-1", "accept_terms": True},
        )
        self.assertEqual(response.status_code, 400)

    def test_public_feed_filters_by_purpose_type_location_and_price(self):
        response = self.client.get(
            "/api/listings?purpose=rent&type=شقة&location=حاسي%20بحبح&max_price=50000&min_rooms=3"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["items"]), 1)
        self.assertEqual(response.json["items"][0]["location"], "حاسي بحبح")

        invalid_price = self.client.get("/api/listings?max_price=not-a-number")
        self.assertEqual(invalid_price.status_code, 400)
        invalid_rooms = self.client.get("/api/listings?min_rooms=not-a-number")
        self.assertEqual(invalid_rooms.status_code, 400)

    def test_admin_routes_require_the_configured_key(self):
        response = self.client.get("/api/admin/listings")
        self.assertEqual(response.status_code, 401)
        response = self.client.get(
            "/api/admin/listings", headers={"X-Admin-Key": "test-admin-key"}
        )
        self.assertEqual(response.status_code, 200)

    def test_phone_password_authentication_uses_csrf_and_hashed_passwords(self):
        csrf = self.client.get("/api/auth/me").json["csrf_token"]
        registration = self.client.post(
            "/api/auth/register",
            json={"name": "مستخدم تجريبي", "phone": "0778000000", "password": "strong-pass-1"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(registration.status_code, 201)
        self.assertEqual(registration.json["user"]["phone"], "0778000000")
        connection = sqlite3.connect(app.config["DATABASE"])
        try:
            password_hash = connection.execute("SELECT password_hash FROM users").fetchone()[0]
        finally:
            connection.close()
        self.assertNotEqual(password_hash, "strong-pass-1")

        duplicate = self.client.post(
            "/api/auth/register",
            json={"name": "مستخدم آخر", "phone": "0778000000", "password": "strong-pass-1"},
            headers={"X-CSRF-Token": registration.json["csrf_token"]},
        )
        self.assertEqual(duplicate.status_code, 409)

        logout = self.client.post(
            "/api/auth/logout",
            json={},
            headers={"X-CSRF-Token": registration.json["csrf_token"]},
        )
        self.assertEqual(logout.status_code, 200)
        login = self.client.post(
            "/api/auth/login",
            json={"phone": "0778000000", "password": "strong-pass-1"},
            headers={"X-CSRF-Token": logout.json["csrf_token"]},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").json["user"]["name"], "مستخدم تجريبي")

    def test_listing_images_are_saved_with_safe_generated_names(self):
        form = {
            "title": "منزل مع صور",
            "location": "الجلفة",
            "phone": "0550000000",
            "type": "بيت",
            "purpose": "sale",
            "price": "12000000",
            "accept_terms": "on",
            "images": (BytesIO(b"\x89PNG\r\n\x1a\nsample-image"), "unsafe<script>.png"),
        }
        response = self.client.post("/api/listings", data=form, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 201)
        connection = sqlite3.connect(app.config["DATABASE"])
        try:
            image_url = connection.execute(
                "SELECT image FROM listings WHERE id = ?", (response.json["id"],)
            ).fetchone()[0]
        finally:
            connection.close()
        image_path = Path(app.config["UPLOAD_DIR"]) / Path(image_url).name
        self.assertTrue(image_path.exists())
        self.assertNotIn("<script>", image_path.name)
        image_response = self.client.get(image_url)
        self.assertEqual(image_response.status_code, 200)
        image_response.close()

    def test_comments_require_login_and_stay_hidden_until_moderated(self):
        listing = {
            "title": "منزل للتعليق",
            "location": "الجلفة",
            "phone": "0550000000",
            "type": "بيت",
            "purpose": "sale",
            "price": "12000000",
            "accept_terms": True,
        }
        created = self.client.post("/api/listings", json=listing)
        self.assertEqual(created.status_code, 201)
        listing_id = created.json["id"]
        admin_headers = {"X-Admin-Key": "test-admin-key"}
        self.client.post(f"/api/admin/listings/{listing_id}/approve", headers=admin_headers)

        csrf = self.client.get("/api/auth/me").json["csrf_token"]
        unauthorized = self.client.post(
            f"/api/listings/{listing_id}/comments",
            json={"body": "تعليق مفيد"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(unauthorized.status_code, 401)

        registration = self.client.post(
            "/api/auth/register",
            json={"name": "معلق", "phone": "0778111222", "password": "strong-pass-2"},
            headers={"X-CSRF-Token": csrf},
        )
        comment = self.client.post(
            f"/api/listings/{listing_id}/comments",
            json={"body": "تعليق مفيد"},
            headers={"X-CSRF-Token": registration.json["csrf_token"]},
        )
        self.assertEqual(comment.status_code, 201)
        self.assertEqual(len(self.client.get(f"/api/listings/{listing_id}/comments").json["items"]), 0)

        pending = self.client.get("/api/admin/comments", headers=admin_headers)
        self.assertEqual(len(pending.json["items"]), 1)
        approved = self.client.post(
            f"/api/admin/comments/{comment.json['id']}/approve", headers=admin_headers
        )
        self.assertEqual(approved.status_code, 200)
        comments = self.client.get(f"/api/listings/{listing_id}/comments").json["items"]
        self.assertEqual(comments[0]["body"], "تعليق مفيد")


if __name__ == "__main__":
    unittest.main()
