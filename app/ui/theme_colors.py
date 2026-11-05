"""How each original OpenSourceTree colour translates to an Equestria theme.

The sources (style.qss, Designer forms, inline styles) keep their original
purple colours, so the base theme is exactly what it always was. When an
Equestria theme is active, every original colour is looked up here.

A value is either a theme role ("text", "accent2", ...) or a tuple
(first, second, amount): first mixed towards second by amount (0..1).
Besides the twelve kit roles there are three computed ones:
  sel         — selection / primary-button fill (accent toned down so text stays readable)
  on_sel      — text drawn on top of sel
  accent_text — accent made readable as text on the window background

The original panels are *lighter* than the window (mantle in the kit is
darker), so panel shades are mixes of base towards surface0, not mantle.
"""

LEGACY_COLORS = {
    # ── Surfaces, darkest to lightest ────────────────────────────────────
    '#161424': 'crust',                               # menu bar, status bar
    '#1a1829': 'base',                                # window
    '#1c1a2c': ('base', 'surface0', 0.15),
    '#1e1c30': ('base', 'surface0', 0.30),            # panels
    '#232034': ('base', 'surface0', 0.55),
    '#231e37': ('base', 'surface0', 0.55),            # menus
    '#26233a': ('base', 'surface0', 0.80),
    '#28233c': 'surface0',
    '#28243e': 'surface0',                            # inputs
    '#2c2844': ('surface0', 'surface1', 0.30),
    '#322c48': ('surface0', 'surface1', 0.60),
    '#322d4b': ('surface0', 'surface1', 0.60),        # borders, splitters
    '#37324b': ('surface0', 'surface1', 0.75),
    '#3c325a': 'surface1',                            # hover
    '#463764': ('surface1', 'surface2', 0.50),
    '#503c6e': 'surface2',
    '#504173': 'surface2',
    '#503c78': 'surface2',
    '#645a82': ('surface2', 'subtext', 0.35),         # disabled text, placeholders
    '#321e50': ('surface0', 'sel', 0.35),
    '#50286e': ('surface1', 'sel', 0.60),
    '#1e1e1e': 'mantle',                              # diff background
    '#272822': 'mantle',                              # Pygments monokai background
    '#49483e': 'surface1',
    '#3c3c3c': 'surface1',                            # separators

    # ── Accent fills and accent text ─────────────────────────────────────
    '#64328c': 'sel',                                 # selection, primary buttons
    '#7846a0': ('sel', 'accent', 0.15),
    '#785aa0': ('sel', 'accent', 0.25),
    '#785ab4': ('sel', 'accent', 0.35),               # focus borders
    '#8c46be': ('sel', 'accent', 0.45),
    '#a05ad2': ('sel', 'accent', 0.60),
    '#a064d2': ('sel', 'accent', 0.60),
    '#cba6f7': 'accent_text',                         # toolbar text, links
    '#ae81ff': 'accent_text',
    '#b49bdc': ('accent_text', 'text', 0.40),
    '#ffffff': 'on_sel',                              # every white in the app sits on sel

    # ── Text ──────────────────────────────────────────────────────────────
    '#dcd7f5': 'text',
    '#d4d4d4': 'text',
    '#f8f8f2': 'text',
    '#8c78b4': 'subtext',
    '#888888': 'subtext',
    '#aaaaaa': 'subtext',
    '#75715e': 'subtext',
    '#a59f85': 'subtext',
    '#7a6e9e': ('subtext', 'surface2', 0.40),
    '#666666': ('subtext', 'surface2', 0.50),

    # ── Status and syntax ────────────────────────────────────────────────
    '#4ec9b0': 'green',
    '#a6e3a1': 'green',
    '#a0dc82': 'green',
    '#80cc80': 'green',
    '#a8e0a8': 'green',
    '#a6e22e': 'green',
    '#6a9955': ('green', 'subtext', 0.50),            # comments
    '#8cb48c': ('green', 'subtext', 0.40),
    '#f44747': 'red',
    '#f38ba8': 'red',
    '#ff6464': 'red',
    '#ff8080': 'red',
    '#f92672': 'red',
    '#ff9696': ('red', 'text', 0.35),
    '#ffb0b0': ('red', 'text', 0.35),
    '#dcdcaa': 'yellow',
    '#f9e2af': 'yellow',
    '#e0d060': 'yellow',
    '#e6db74': 'yellow',
    '#ce9178': ('yellow', 'red', 0.35),               # authors, strings, stashes
    '#f5a623': ('yellow', 'red', 0.35),
    '#e6aa5a': ('yellow', 'red', 0.35),
    '#ff9664': ('yellow', 'red', 0.35),
    '#ff8c6e': ('yellow', 'red', 0.35),
    '#fab387': ('yellow', 'red', 0.35),
    '#9cdcfe': ('accent2', 'text', 0.45),             # hashes, remote branches
    '#569cd6': 'accent2',                             # keywords, hunk headers
    '#66d9ef': 'accent2',
    '#89dceb': ('accent2', 'text', 0.30),
    '#89b4fa': ('accent2', 'text', 0.30),
    '#94e2d5': ('accent2', 'text', 0.30),
    '#6464b4': 'accent2',                             # info frame, used with alpha

    # ── Tinted backgrounds ───────────────────────────────────────────────
    '#1a3a2a': ('base', 'green', 0.15),               # added lines
    '#1a3a1a': ('base', 'green', 0.15),
    '#1a2e1a': ('base', 'green', 0.12),
    '#3a1a1a': ('base', 'red', 0.15),                 # removed lines
    '#4a1a1a': ('base', 'red', 0.18),
    '#2e1a1a': ('base', 'red', 0.12),
    '#3a3a10': ('base', 'yellow', 0.15),
    '#371914': ('base', 'red', 0.15),                 # conflict banner
    '#a03c37': ('base', 'red', 0.50),
    '#264f78': ('base', 'accent2', 0.30),             # highlighted line
}

# Categorical colours that read on any dark background and are kept as is.
KEPT_AS_IS = {'#285a8c', '#503c14', '#286e3c'}       # remote / tag / HEAD badges
