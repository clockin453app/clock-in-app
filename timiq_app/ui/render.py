from pathlib import Path

from flask import current_app, render_template, render_template_string
from jinja2 import TemplateNotFound


def _render_template_safely(template_name: str, **context):
    try:
        return render_template(template_name, **context)
    except TemplateNotFound:
        root_path = Path(current_app.root_path)
        project_root = root_path.parent

        candidates = [
            root_path / "templates" / template_name,
            project_root / "timiq_app" / "templates" / template_name,
            Path.cwd() / "timiq_app" / "templates" / template_name,
            Path.cwd() / "templates" / template_name,
        ]

        for path in candidates:
            if path.exists() and path.is_file():
                source = path.read_text(encoding="utf-8")
                template = current_app.jinja_env.from_string(source)
                return template.render(**context)

        checked = "\n".join(str(p) for p in candidates)
        raise TemplateNotFound(
            f"{template_name}. Checked:\n{checked}"
        )


def render_page(
    *,
    template_name: str,
    active: str,
    role: str,
    layout_shell,
    style: str,
    viewport: str,
    pwa_tags: str,
    page_css: str = "",
    **context,
):
    """
    Transitional renderer.

    Important:
    page_css is appended after layout_shell so page-specific design can win
    over the late global reference CSS.
    """
    content_html = _render_template_safely(template_name, **context)

    late_page_css = ""
    if page_css:
        late_page_css = f'\n<link rel="stylesheet" href="{page_css}">\n'

    final_clean_css = '\n<link rel="stylesheet" href="/static/css/pages/admin-final-clean.css?v=12">\n'

    return render_template_string(
        f"{style}{viewport}{pwa_tags}" +
        layout_shell(active, role, content_html) +
        late_page_css +
        final_clean_css
    )