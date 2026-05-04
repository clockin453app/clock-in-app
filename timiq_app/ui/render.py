from pathlib import Path
import re

from flask import current_app, render_template, render_template_string
from jinja2 import TemplateNotFound


_STYLESHEET_LINK_RE = re.compile(
    r'\s*(<link\b(?=[^>]*\brel=["\']stylesheet["\'])(?=[^>]*\bhref=)[^>]*>)\s*',
    re.IGNORECASE,
)

_HREF_RE = re.compile(r'\bhref=(["\'])(.*?)\1', re.IGNORECASE)


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


def _extract_stylesheet_links(html: str):
    """
    Move stylesheet links out of page body content so CSS loads before the page paints.
    This prevents icon/layout flashes during navigation.
    """
    links = []
    seen_hrefs = set()

    def replace_link(match):
        tag = match.group(1)
        href_match = _HREF_RE.search(tag)

        if not href_match:
            return "\n"

        href = href_match.group(2)
        key = href.split("?", 1)[0]

        if key not in seen_hrefs:
            seen_hrefs.add(key)
            links.append(tag)

        return "\n"

    cleaned_html = _STYLESHEET_LINK_RE.sub(replace_link, html or "")
    return links, cleaned_html


def _stylesheet_tag(href: str):
    return f'<link rel="stylesheet" href="{href}">'


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
    content_html = _render_template_safely(template_name, **context)

    stylesheet_links, content_html = _extract_stylesheet_links(content_html)

    if not any("admin-final-clean.css" in link for link in stylesheet_links):
        stylesheet_links.append(
            _stylesheet_tag("/static/css/pages/admin-final-clean.css?v=12")
        )
    if not any("mobile-fit.css" in link for link in stylesheet_links):
        stylesheet_links.append(
            _stylesheet_tag("/static/css/pages/mobile-fit.css?v=1")
        )

    if page_css:
        stylesheet_links.append(_stylesheet_tag(page_css))

    head_stylesheets = "\n".join(stylesheet_links)

    return render_template_string(
        f"{style}{viewport}{pwa_tags}\n{head_stylesheets}\n"
        + layout_shell(active, role, content_html)
    )