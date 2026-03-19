from datetime import date, datetime

from werkzeug.security import generate_password_hash

from workhours_app import create_app
from workhours_app.extensions import db
from workhours_app.models import Employee, Location, WorkHour, WorkplaceSetting

app = create_app()

with app.app_context():
    db.create_all()

    if not WorkplaceSetting.query.filter_by(workplace_id="default").first():
        db.session.add(
            WorkplaceSetting(
                workplace_id="default",
                company_name="NEVERA",
                currency_symbol="£",
                tax_rate=20,
            )
        )

    if not Employee.query.filter_by(username="admin@example.com").first():
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

    if not Employee.query.filter_by(username="employee@example.com").first():
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

    if not Location.query.filter_by(site_name="MAIN", workplace_id="default").first():
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

    if not WorkHour.query.filter_by(employee_email="admin@example.com", workplace_id="default").first():
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

    if not WorkHour.query.filter_by(employee_email="employee@example.com", workplace_id="default").first():
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

    db.session.commit()
    print("Seeded local test data.")