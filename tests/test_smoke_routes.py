from tests.conftest import login


def test_ping(client):
    response = client.get('/ping')
    assert response.status_code == 200
    assert response.get_data(as_text=True) == 'pong'


def test_manifest(client):
    response = client.get('/manifest.webmanifest')
    assert response.status_code == 200
    data = response.get_json()
    assert data['name'] == 'WorkHours'
    assert data['icons']


def test_login_page_renders_template_assets(client):
    response = client.get('/login')
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '/static/css/app.css' in body
    assert '<form method="POST">' in body


def test_employee_login_and_core_pages(client):
    response = login(client, 'employee@example.com')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/')

    dashboard = client.get('/')
    assert dashboard.status_code == 200
    assert 'Dashboard' in dashboard.get_data(as_text=True)

    clock = client.get('/clock')
    assert clock.status_code == 200
    assert 'Clock In' in clock.get_data(as_text=True)

    times = client.get('/my-times')
    assert times.status_code == 200
    assert 'Time logs' in times.get_data(as_text=True)

    reports = client.get('/my-reports')
    assert reports.status_code == 200
    assert 'Timesheets' in reports.get_data(as_text=True)


def test_admin_login_and_admin_pages(client):
    response = login(client, 'admin@example.com')
    assert response.status_code == 302

    for path, marker in [
        ('/admin', 'Admin'),
        ('/admin/payroll', 'Payroll Report'),
        ('/admin/locations', 'Locations'),
        ('/admin/employees', 'Create Employee'),
        ('/admin/employee-sites', 'Employee Sites'),
        ('/admin/workplaces', 'Workplaces'),
    ]:
        page = client.get(path)
        assert page.status_code == 200, path
        assert marker in page.get_data(as_text=True), path
