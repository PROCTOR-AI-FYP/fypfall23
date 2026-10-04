# Frontend redesign verification

This redesign changes frontend source only. Backend, AI engine, API client,
authentication providers, production routing, dependencies and runtime scripts
were compared with their hashes at the start of this task and left unchanged.

## Design

- Shared floating navigation, contextual portal introductions, glass panels,
  refreshed tables, forms, badges, notifications and dialogs across all five roles.
- Sign-in redesign and a small landing-page visual update.
- Light, dark and system themes; responsive navigation and layouts.
- Lightweight CSS 3D sculpture with pointer tilt and reduced-motion support.
- React Bits SpotlightCard, StarBorder and CountUp. Their licence is retained in
  `../components/reactbits/LICENSE.md`. No new package dependencies.

## Checks

- Production TypeScript / Vite build passes. Vite still warns about a main chunk
  slightly above 500 kB.
- Lint exits successfully with existing React hook warnings.
- All 23 portal route views render on desktop and at 390 px width, with no page
  horizontal overflow or error boundary. Table overflow is contained inside cards.
- Sign-in and landing checked on desktop and mobile; light/dark appearance checked.
- Search filtering, keyboard table sorting, modal Escape dismissal / focus return,
  mobile drawer Escape dismissal / focus return, and notifications checked.
- The real signed-in admin dashboard also renders with the redesigned components.

## Safe visual preview

`preview.html` is a separate, development-only entry point. It renders the actual
page components using existing sample records and intercepts API requests in that
tab only. Writes are rejected. It does not seed data, sign into accounts or change
the backend, and is not imported into the production app or build entry point.

Examples on the running Vite server:

- `/src/dev/preview.html?role=admin`
- `/src/dev/preview.html?role=hod`
- `/src/dev/preview.html?role=teacher`
- `/src/dev/preview.html?role=student`
- `/src/dev/preview.html?role=exam_controller`
- `/src/dev/preview.html?view=%2Flogin`

Preview results verify presentation and frontend interactions. They do not replace
the project's existing backend or camera integration tests.
