"""The stylesheet's files exist, and the logo never melts into the login panel."""
import re
from pathlib import Path

STATIC = Path(__file__).parent.parent / "hirewire" / "static"
CSS = (STATIC / "style.css").read_text(encoding="utf-8")


def test_every_file_the_stylesheet_loads_exists():
    paths = re.findall(r'url\("([^"]+)"\)', CSS)
    assert paths, "the fonts should be loaded with url(...)"
    missing = [path for path in paths if not (STATIC / path).exists()]
    assert missing == []


def test_the_pages_preload_the_heading_font(client):
    page = client.get("/login").get_data(as_text=True)
    preloaded = re.search(r'<link rel="preload" href="/static/(fonts/[^"]+)"', page).group(1)
    assert f'url("{preloaded}")' in CSS


def test_the_login_panel_has_its_own_colour_in_every_theme():
    # Light, the device's dark mode, and dark chosen in Settings.
    assert len(re.findall(r"--panel: #[0-9a-f]{6};", CSS)) == 3
    assert ".welcome-panel { background: var(--panel);" in CSS


def test_the_logo_tile_is_solid_on_the_panel():
    panel_mark = re.search(r"\.welcome-panel \.wordmark \.mark \{([^}]+)\}", CSS).group(1)
    assert "color: #fff" in panel_mark and "--mark-wire: var(--panel)" in panel_mark
    assert "rgb(255 255 255 /" not in panel_mark  # see-through is what made it disappear
