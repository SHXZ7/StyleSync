@AGENTS.md

## Project: StyleSync Frontend

### Stack
- Next.js (App Router) with TypeScript
- Tailwind CSS + PostCSS
- ESLint configured

### File structure conventions
- Pages and layouts live in `app/` using the App Router convention
- Components go in `app/components/` or `components/`
- Shared utilities in `lib/` or `utils/`
- API calls in `services/` or `lib/api/`

### Code style
- Use JavaScript for all new files
- Prefer server components by default; add `"use client"` only when needed
- Use Tailwind utility classes; avoid inline styles
- Use named exports for components

### Common commands
- `npm run dev` — start dev server
- `npm run build` — production build
- `npm run lint` — run ESLint

### Key rules for Claude
- Check `node_modules/next/dist/docs/` for Next.js API reference before writing routing or data fetching code
- Do not use `getServerSideProps` or `getStaticProps` — this is App Router
- Use `fetch` with cache options, not `axios`, unless already in package.json
- Backend is in `/backend` — check there before adding API routes to frontend