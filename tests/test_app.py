import os, tempfile, unittest
os.environ["SECRET_KEY"] = "test-secret-key"
fd, path = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.environ["DATABASE_PATH"] = path
import app as busapp

class BusPassTests(unittest.TestCase):
    def setUp(self):
        busapp.app.config["TESTING"] = True
        self.client = busapp.app.test_client()

    def tearDown(self):
        pass

    def register_and_login(self):
        self.client.post("/register", data={"name":"Test User","email":"test@example.com","password":"password123"}, follow_redirects=True)
        return self.client.post("/login", data={"email":"test@example.com","password":"password123"}, follow_redirects=True)

    def test_home_and_health(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_register_login_and_booking(self):
        self.register_and_login()
        with busapp.app.app_context():
            route = busapp.db().execute("SELECT id FROM routes LIMIT 1").fetchone()
        response = self.client.post(f"/book/{route['id']}", data={"passenger_name":"Test User","seats":"1"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"BOOKING CONFIRMED", response.data)

if __name__ == "__main__":
    unittest.main()
