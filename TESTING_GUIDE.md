# Refactor testing guide

## Goal
Test the refactor without replacing the current working app.

## Recommended setup for your environment
- Keep the current working app on the `main` branch.
- Put the refactor on a separate branch such as `refactor-test`.
- Create a second Render web service from the same GitHub repo, but point it to `refactor-test`.
- Keep your current custom domain on the current working app.
- Use the default Render URL for the refactor test service.

## Local smoke test first
1. Open the refactor project in PyCharm as a separate folder.
2. Create a new virtual environment.
3. Install `requirements.txt`.
4. Copy the environment variables from Render into a local `.env` or PyCharm run configuration.
5. Use a copied test database, not the production one.
6. Run `app.py` locally.

## Render smoke test second
1. Push the refactor branch to GitHub.
2. Create a second Render service from that branch.
3. Copy the same environment variables from the current service.
4. Change only the risky values if possible:
   - `DATABASE_URL`
   - upload folder / disk path
   - Google Sheet ID
   - Google Drive folder ID
   - `SECRET_KEY`
5. Deploy the second service.
6. Test login, dashboard, clock, timesheets, payroll, locations, employees, employee sites, and workplaces.

## Minimum manual checks
- Employee login works.
- Admin login works.
- Dashboard loads.
- Clock page loads and map appears.
- Time logs page loads.
- Timesheets page loads.
- Admin page loads.
- Payroll report loads.
- Locations page loads.
- Employees page loads.
- Employee sites page loads.
- Workplaces page loads.

## Test status in this patched refactor
Automated smoke tests currently cover:
- app import / bootstrap
- manifest
- login page assets
- employee login + dashboard / clock / time logs / timesheets
- admin login + admin / payroll / locations / employees / employee sites / workplaces
