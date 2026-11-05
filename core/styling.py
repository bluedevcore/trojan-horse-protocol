"""Neutral, professional styling shared by every demo (no client branding)."""

PALETTE = {
    "ink": "#1F2933",
    "muted": "#5B6775",
    "border": "#D9DEE5",
    "surface": "#F6F7F9",
    "accent": "#2F5D8A",
    "high": "#B42318",
    "medium": "#B54708",
    "low": "#475467",
    "ok": "#027A48",
}

CSS = """
<style>
:root {
  --ink: %(ink)s; --muted: %(muted)s; --border: %(border)s; --surface: %(surface)s;
  --accent: %(accent)s; --high: %(high)s; --medium: %(medium)s; --low: %(low)s; --ok: %(ok)s;
}
.block-container { max-width: 1200px; padding-top: 1.6rem; padding-bottom: 3rem; }
#MainMenu, footer, [data-testid="stDecoration"] { visibility: hidden; height: 0; }
h1, h2, h3 { color: var(--ink); letter-spacing: -0.01em; }
.th-headline { font-size: 1.85rem; font-weight: 700; color: var(--ink); margin: 0 0 .25rem 0; line-height: 1.25; }
.th-replaces { color: var(--muted); font-size: 1.02rem; margin: 0 0 .6rem 0; }
.th-badges { display: flex; gap: .4rem; flex-wrap: wrap; margin-bottom: .4rem; }
.th-badge { font-size: .74rem; padding: .14rem .55rem; border-radius: 999px; border: 1px solid var(--border);
            color: var(--muted); background: #fff; white-space: nowrap; }
.th-badge.mock { border-color: #E9C46A; background: #FFF8E6; color: #7A5B00; font-weight: 600; }
.th-badge.live { border-color: #A6D8BF; background: #ECFDF3; color: var(--ok); font-weight: 600; }
.th-section { font-size: 1.12rem; font-weight: 650; color: var(--ink); margin: 1.4rem 0 .2rem 0;
              padding-top: .6rem; border-top: 1px solid var(--border); }
.th-caption { color: var(--muted); font-size: .88rem; margin-bottom: .6rem; }

/* step progress */
.th-steps { list-style: none; padding: .7rem .9rem; margin: .4rem 0 1rem 0; background: var(--surface);
            border: 1px solid var(--border); border-radius: 8px; }
.th-steps li { padding: .22rem 0; color: var(--ink); font-size: .95rem; display: flex; gap: .55rem; align-items: baseline; }
.th-steps li .ic { width: 1.1rem; text-align: center; font-weight: 700; flex: none; }
.th-steps li.done .ic { color: var(--ok); }
.th-steps li.warn .ic { color: var(--medium); }
.th-steps li.fail .ic { color: var(--high); }
.th-steps li.running { color: var(--accent); font-weight: 600; }
.th-steps li .detail { color: var(--muted); font-size: .85rem; }
.th-spin { display: inline-block; width: .8rem; height: .8rem; border: 2px solid #C7D3E0; border-top-color: var(--accent);
           border-radius: 50%%; animation: th-spin .8s linear infinite; }
@keyframes th-spin { to { transform: rotate(360deg); } }

/* summary panel */
.th-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: .6rem; margin: .5rem 0 .8rem 0; }
.th-metric { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: .65rem .8rem; }
.th-metric .v { font-size: 1.45rem; font-weight: 700; color: var(--ink); line-height: 1.2; }
.th-metric .l { font-size: .8rem; color: var(--muted); margin-top: .1rem; }
.th-metric .s { font-size: .74rem; color: var(--muted); margin-top: .15rem; }
.th-metric.alert { border-left: 4px solid var(--high); }
.th-metric.good { border-left: 4px solid var(--ok); }
.th-summary { background: var(--surface); border: 1px solid var(--border); border-left: 4px solid var(--accent);
              border-radius: 8px; padding: .8rem 1rem; color: var(--ink); font-size: .98rem; line-height: 1.5; }
.th-summary .src { color: var(--muted); font-size: .75rem; margin-top: .4rem; }

/* needs human check */
.th-check { border: 1px solid var(--border); border-radius: 8px; padding: .55rem .8rem; margin-bottom: .45rem; background: #fff; }
.th-check .t { font-weight: 650; color: var(--ink); }
.th-check .w { color: var(--ink); font-size: .9rem; margin-top: .15rem; }
.th-check .a { color: var(--muted); font-size: .85rem; margin-top: .15rem; }
.th-pill { display: inline-block; font-size: .7rem; font-weight: 700; padding: .05rem .45rem; border-radius: 4px;
           margin-right: .45rem; color: #fff; vertical-align: 1px; text-transform: uppercase; letter-spacing: .02em; }
.th-pill.high { background: var(--high); } .th-pill.medium { background: var(--medium); } .th-pill.low { background: var(--low); }
.th-pill.info { background: var(--accent); }

div[data-testid="stDownloadButton"] button { width: 100%%; }
div.stButton > button[kind="primary"] { font-size: 1.05rem; padding: .6rem 1.4rem; }
</style>
""" % PALETTE
