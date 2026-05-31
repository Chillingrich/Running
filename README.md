# 🏃 Running Analytics Dashboard

Personal running analytics for Pomparazzi | Sub-3 Marathon Target | Phuket 2026

## Setup

### 1. Enable GitHub Pages
Settings → Pages → Source: `main` branch → `/root` → Save

Dashboard will be at: `https://chillingrich.github.io/Running/dashboard.html`

### 2. Connect Dashboard to GitHub
1. Create a Personal Access Token: https://github.com/settings/tokens/new
   - Scopes: `repo` (full control)
2. Open dashboard → click **⚙ GitHub** button → paste token

### 3. Upload FIT Files
- Go to `fits/` folder on GitHub
- Click **Add file** → **Upload files**
- Drop your `.fit` files
- GitHub Actions will auto-parse → update `data/sessions.json` → dashboard refreshes

## Workflow

```
Upload .fit to GitHub → Action parses → sessions.json updated → Dashboard loads automatically
```

## Files

| File | Purpose |
|---|---|
| `dashboard.html` | Main analytics dashboard |
| `parser.py` | FIT file parser (runs in GitHub Actions) |
| `data/sessions.json` | Parsed session data (auto-generated) |
| `fits/` | Upload .fit files here |
| `.github/workflows/parse_fits.yml` | Auto-parse trigger |

## Zones (Coros Lactate Threshold)

| Zone | HR | Pace |
|---|---|---|
| Z1 Recovery | <130 | >5:36 |
| Z2 Aerobic End. | 130–147 | 4:41–5:36 |
| Z3 Aerobic Pwr | 148–155 | 4:19–4:40 |
| Z4 Threshold | 156–166 | 3:56–4:18 |
| Z5 Anaerobic End. | 167–173 | 3:37–3:55 |
| Z6 Anaerobic Pwr | >173 | <3:37 |
