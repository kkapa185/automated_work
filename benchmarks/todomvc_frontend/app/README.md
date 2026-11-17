# TodoMVC — vanilla JavaScript

A TodoMVC implementation built from `spec/app-spec.md` with modern vanilla JS (ES modules, no framework, no build step).

## Run
```
./serve --port 8080      # then open http://127.0.0.1:8080/
```
`serve` is a dependency-free Node (>=18) static server bound to 127.0.0.1. Only `index.html`, `css/` and `js/` are served.

## Test
```
npm install              # installs Playwright test runner (+ todomvc-app-css, todomvc-common per spec)
npx playwright install chromium   # only if no browser is available yet
npm test                 # Playwright end-to-end tests; starts ./serve on port 4173 (override: TODOMVC_PORT)
```
Tests are named by requirement id (R1–R16, see `.orchestrator/requirements.md`).

## Design
- `js/models/todo-model.js` — state, filtering at model level, persistence to `localStorage` key `todos-vanillajs` (`[{id,title,completed}]`); corrupt data is treated as empty.
- `js/views/todo-view.js` — renders from the model using DOM APIs/`textContent` (no HTML injection).
- `js/controllers/todos.js` — event wiring and hash routing (`#/`, `#/active`, `#/completed`, `#!/` variants). The filter is derived from `location.hash`, so reload and back/forward work. Editing: Enter/blur saves, Escape cancels, empty title deletes.
- `css/index.css` is the official `todomvc-app-css` stylesheet, vendored (no CDN); `css/app.css` holds minimal overrides. `todomvc-common` is declared as a dependency per the spec but not used at runtime.
