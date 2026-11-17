# FE-12: TodoMVC — the reference to-do list web application (vanilla JavaScript)

Build a TodoMVC application that satisfies the official TodoMVC application specification provided in
`spec/app-spec.md` (functionality, keyboard behaviour, routing, persistence) using the standard TodoMVC
HTML structure and class names (`.todoapp`, `.new-todo`, `.main`, `.toggle-all`, `.todo-list` with
`li` items containing `.view` → `.toggle`, `label`, `.destroy` and the `.edit` input in editing mode,
`li.completed`, `li.editing`, `.footer`, `.todo-count` with a `<strong>` count and correct
pluralisation, `.filters` links `#/`, `#/active`, `#/completed` with `a.selected` on the active one,
`.clear-completed`). Use the official look: the `todomvc-app-css` styles (vendored into the project —
no CDN at runtime).

Constraints: modern vanilla JavaScript (ES modules, no framework), no runtime network access, data
persisted in `localStorage` (survives reload), hash-based routing that respects the browser back
button, items rendered in insertion order.

Runtime contract: `./serve --port <port>` serves the app at `http://127.0.0.1:<port>/` (a static file
server is enough). Provide automated end-to-end tests (e.g. Playwright) for every behaviour in the
spec, and a README.
