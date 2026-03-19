import os
import pathlib
import re
import sys
from datetime import date, datetime

import pytest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENABLE_SHEETS_RUNTIME", "0")
os.environ.setdefault("ENABLE_SHEETS_IMPORT", "0")
os.environ.setdefault("AUTO_CREATE_DB_SCHEMA", "0")

from workhours_app import create_app  # noqa: E402
from workhours_app.extensions import db  # noqa: E402
from workhours_app.models import Employee, Location, WorkHour, WorkplaceSetting  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402


app = create_app()


@pytest.fixture()
def client():
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.app_context():
        db.drop_all()
        db.create_all()
        db.session.add(
            WorkplaceSetting(
                workplace_id="default",
                company_name="NEVERA",
                currency_symbol="£",
                tax_rate=20,
            )
        )
        db.session.add(
            Employee(
                email="employee@example.com",
                username="employee@example.com",
                name="Employee User",
                first_name="Employee",
                last_name="User",
                role="employee",
                workplace="default",
                workplace_id="default",
                password=generate_password_hash("password123"),
                active="true",
                rate=10,
            )
        )
        db.session.add(
            Employee(
                email="admin@example.com",
                username="admin@example.com",
                name="Admin User",
                first_name="Admin",
                last_name="User",
                role="master_admin",
                workplace="default",
                workplace_id="default",
                password=generate_password_hash("password123"),
                active="true",
                rate=20,
            )
        )
        db.session.add(
            Location(
                site_name="MAIN",
                lat=51.55244,
                lon=0.07988,
                radius_meters=70,
                active="TRUE",
                workplace_id="default",
            )
        )
        db.session.add(
            WorkHour(
                employee_email="employee@example.com",
                date=date(2026, 3, 19),
                clock_in=datetime(2026, 3, 19, 8, 0, 0),
                clock_out=datetime(2026, 3, 19, 17, 0, 0),
                workplace="default",
                workplace_id="default",
                hours=8.5,
                pay=85,
            )
        )
        db.session.add(
            WorkHour(
                employee_email="admin@example.com",
                date=date(2026, 3, 19),
                clock_in=datetime(2026, 3, 19, 8, 0, 0),
                clock_out=datetime(2026, 3, 19, 17, 0, 0),
                workplace="default",
                workplace_id="default",
                hours=8.5,
                pay=170,
            )
        )
        db.session.commit()
    with app.test_client() as client:
        yield client


def login(client, username: str, password: str = "password123", workplace_id: str = "default"):
    page = client.get("/login")
    body = page.get_data(as_text=True)
    csrf = re.search(r'name="csrf" value="([^"]+)"', body).group(1)
    return client.post(
        "/login",
        data={
            "csrf": csrf,
            "username": username,
            "password": password,
            "workplace_id": workplace_id,
        },
        follow_redirects=False,
    )
