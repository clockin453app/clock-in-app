import os
import json


def get_import_sheet_by_name(sheet_name: str, mapping: dict):
    key = str(sheet_name or "").strip().lower()
    ws = mapping.get(key)
    if ws is not None:
        return ws

    raise RuntimeError(
        f"Google Sheets worksheet '{sheet_name}' is not available. "
        f"This runtime is DB-backed or Sheets import is disabled."
    )


def init_google_sheets_runtime(
    enable_google_sheets: bool,
    gspread_mod,
    sa_credentials_cls,
    creds_json: str,
    scopes,
    spreadsheet_id: str,
    logger,
):
    state = {
        "creds": None,
        "client": None,
        "spreadsheet": None,
        "employees_sheet": None,
        "work_sheet": None,
        "payroll_sheet": None,
        "onboarding_sheet": None,
        "settings_sheet": None,
        "audit_sheet": None,
        "locations_sheet": None,
    }

    if not enable_google_sheets:
        return state

    if gspread_mod is None or sa_credentials_cls is None:
        raise RuntimeError("Google Sheets runtime/import is enabled but required Google libraries are not installed.")

    try:
        if creds_json:
            service_account_info = json.loads(creds_json)
            creds = sa_credentials_cls.from_service_account_info(service_account_info, scopes=scopes)
        else:
            credentials_file = "credentials.json"
            if not os.path.exists(credentials_file):
                raise FileNotFoundError("credentials.json not found locally and GOOGLE_CREDENTIALS not set.")
            creds = sa_credentials_cls.from_service_account_file(credentials_file, scopes=scopes)
        state["creds"] = creds
        client = gspread_mod.authorize(creds)

        if spreadsheet_id:
            spreadsheet = client.open_by_key(spreadsheet_id)
        else:
            spreadsheet = client.open("WorkHours")

        state["client"] = client
        state["spreadsheet"] = spreadsheet
        state["employees_sheet"] = spreadsheet.worksheet("Employees")
        state["work_sheet"] = spreadsheet.worksheet("WorkHours")
        state["payroll_sheet"] = spreadsheet.worksheet("PayrollReports")
        state["onboarding_sheet"] = spreadsheet.worksheet("Onboarding")

        try:
            state["settings_sheet"] = spreadsheet.worksheet("Settings")
        except Exception:
            state["settings_sheet"] = None

        try:
            state["audit_sheet"] = spreadsheet.worksheet("AuditLog")
        except Exception:
            state["audit_sheet"] = None

        try:
            state["locations_sheet"] = spreadsheet.worksheet("Locations")
        except Exception:
            state["locations_sheet"] = None

    except Exception as e:
        logger.warning("Google Sheets disabled: %s", e)

    return state