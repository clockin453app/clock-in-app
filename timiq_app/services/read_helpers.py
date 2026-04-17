def get_locations_data(use_database, location_model, get_import_sheet):
    if use_database:
        return location_model.query.all()
    return get_import_sheet("locations").get_all_records()


def get_settings_data(use_database, workplace_setting_model, get_import_sheet):
    if use_database:
        return workplace_setting_model.query.all()
    return get_import_sheet("settings").get_all_records()


def get_employees_data(use_database, employee_model, get_import_sheet):
    if use_database:
        return employee_model.query.all()
    return get_import_sheet("employees").get_all_records()