# StyleSync

StyleSync is a web app that scrapes a website and turns its visual language into an editable design system.

It extracts color tokens, typography signals, spacing heuristics, and component styles, then lets users edit, lock, preview, version, and export tokens.

## What It Does

- Ingests a URL and scrapes visual styles using Playwright.
- Extracts:
	- semantic color roles
	- typography scale
	- spacing/radius tokens
	- button/input/card styles
	- image palette (dominant + vibrant)
- Supports lock-and-version workflows with MongoDB Atlas persistence.
- Provides a live editor and instant UI preview.
- Exports tokens as CSS variables, JSON, and Tailwind-friendly config.

## Tech Stack

### Frontend
- Next.js (App Router)
- React
- Tailwind CSS

### Backend
- FastAPI
- Playwright (headless browser scraping)
- Optional Pillow-based screenshot palette fallback
- PyMongo (MongoDB Atlas persistence)

## Project Structure

```
StyleSync/
	backend/
		main.py
		requirements.txt
		.env
		routes/
			scraper_route.py
		services/
			scraper.py
			color_utils.py
			image_analysis.py
			theme_state.py
	frontend/
		app/
			page.js
			layout.js
			globals.css
```

## Key Features

### 1. Intelligent Scraping
- Handles real rendered pages (SPA/SSR/static) through Playwright.
- If scraping is blocked or fails, backend can return simulated fallback analysis (`scrape_mode: simulated`).

### 2. Image Analysis Service
- Dedicated image analysis service (`backend/services/image_analysis.py`).
- Primary path: DOM image sampling.
- Fallback path: screenshot quantization.
- Metadata includes image palette source.

### 3. Token Editor + Live Preview
- Editable semantic colors.
- Editable typography controls (family/size/weight/line-height).
- Spacing visualizer with drag sliders (4px step).
- Lock state per token with visual feedback.
- Instant preview updates.

### 4. Lock + Version + Merge
- Theme state stored in MongoDB Atlas (`stylesync.theme_state` by default).
- Locked tokens persist across re-scrapes.
- New scrapes merge with stored locked overrides.
- Version history tracked for state updates.

### 5. Export
- CSS custom properties
- JSON tokens
- Tailwind config JSON

## API Endpoints

### Scraping
- `POST /scrape?url=<encoded_url>`
	- Returns `system`, `meta`, and persisted `state`.

### Theme State
- `GET /theme-state?url=<encoded_url>`
- `POST /theme-state`

Payload example:

```json
{
	"url": "https://example.com",
	"locked_tokens": ["color.primary"],
	"overrides": {
		"colors": {
			"primary": "#111111"
		}
	}
}
```

### Token CRUD
- `GET /tokens?url=<encoded_url>`
- `PUT /tokens`
- `DELETE /tokens`

## Environment Variables

Backend reads from `backend/.env`.

Required for Atlas persistence:

```env
MONGODB_URI=mongodb+srv://<username>:<password>@<cluster-host>/<dbname>?retryWrites=true&w=majority
```

Optional:

```env
MONGODB_DB=stylesync
MONGODB_COLLECTION=theme_state
```

## Local Setup

## 1) Backend

```bash
cd backend
pip install -r requirements.txt
playwright install
uvicorn main:app --reload
```

Backend runs at `http://127.0.0.1:8000`.

## 2) Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:3000`.

## Storage Verification

When backend starts and first writes state, logs will show:

- Mongo success:
	- `[theme_state] MongoDB connected: <db>.<collection>`
	- `[theme_state] MongoDB upsert success: site_id=..., version=...`
- Local fallback:
	- `[theme_state] MongoDB connection failed; using local JSON store.`

If Atlas UI shows no data:
- Refresh Data Explorer.
- Verify IP access in Atlas Network Access.
- Verify DB user has read/write permissions.

## Current Status

- Frontend and backend workflows are implemented.
- MongoDB Atlas persistence is integrated.
- Runtime behavior depends on valid Atlas connectivity and credentials.

## Security Note

Do not commit real database credentials to Git.
Rotate credentials immediately if they were exposed.
