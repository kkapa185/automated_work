# Requirements — TodoMVC (vanilla JS, ES modules)

## Product
A framework-free TodoMVC web app per `spec/app-spec.md`: standard TodoMVC markup/class names, vendored `todomvc-app-css` (base.css + index.css, no CDN), ES-module JS split into model/controller/view, localStorage persistence (`todos-vanillajs`), hash routing (`#/`, `#/active`, `#/completed`) with back-button support. Served statically via `./serve --port <port>` at `http://127.0.0.1:<port>/`. Includes Playwright e2e tests and a README.

## Acceptance criteria
R1  `./serve --port N` serves index.html at http://127.0.0.1:N/ (static, no network use at runtime; all assets local).
R2  Markup: `section.todoapp` > `header.header` (`h1`, `input.new-todo` autofocus, placeholder "What needs to be done?"), `section.main` (`input.toggle-all`, `ul.todo-list`), `footer.footer` (`span.todo-count` with `<strong>`, `ul.filters` with links `#/`, `#/active`, `#/completed`, `button.clear-completed`).
R3  Items: `li` (class `completed` when done, `editing` when editing) > `div.view` > `input.toggle`(checkbox), `label`(title), `button.destroy`; in editing mode an `input.edit` holds the title.
R4  No todos: `.main` and `.footer` hidden (not visible).
R5  New todo input focused on load; Enter creates todo (title trimmed), appends at end of list (insertion order), clears input; empty/whitespace-only does nothing. Titles are rendered as text (HTML-escaped, no injection).
R6  Toggle checkbox marks complete/incomplete, toggles `li.completed`, updates counter.
R7  Toggle-all sets every todo to its own checked state; it is checked iff there is ≥1 todo and all are completed; updates when single items toggle, are added, or removed; unchecked after Clear completed.
R8  Double-click label enters editing mode: `li.editing`, `.edit` input visible containing the title, focused; other controls hidden.
R9  Edit saves on Enter and on blur (trimmed), removing `editing`; empty trimmed title destroys the todo; Escape leaves edit mode discarding changes (and subsequent blur must not save).
R10 Hovering an item shows `.destroy`; clicking removes the item.
R11 Counter: `<strong>N</strong> item(s) left` with `0 items`, `1 item`, `2 items` (counts active todos).
R12 Clear completed: removes all completed todos; hidden when none completed.
R13 Persistence: todos stored in localStorage key `todos-vanillajs` as JSON array of `{id,title,completed}`; survive reload; editing state not persisted; corrupt/invalid stored data tolerated (treated as empty).
R14 Routing: `#/` all (default; empty hash also), `#/active`, `#/completed` (`#!/…` variants also accepted); list filtered at model level; `a.selected` on the active filter link only; item updates under a filter apply immediately (e.g. checking in Active hides it); the filter is derived from the URL hash so it persists across reload; back/forward buttons navigate between filters.
R15 Toggle-all with a filter active applies to all todos (model level) and the view re-filters.
R16 Footer filter links' `selected` class and counter remain correct when empty-state in a filtered view (main/footer hidden only when zero todos total).
R17 Project: package.json declaring `todomvc-app-css` and `todomvc-common` dependencies (spec) and test scripts; `npm test` runs Playwright e2e; README documents install/run/test/design. Code style: single quotes in JS, double in HTML, `ENTER_KEY`/`ESCAPE_KEY` constants (no raw keyCode), no preprocessors.
R18 Directory layout: `index.html`, `css/app.css`, `js/app.js`, `js/controllers/`, `js/models/`, `js/views/`, vendored `node_modules`-free `assets/` or `css/` copies of base/index styles.

## Assumptions
- Spec's `#main`/`#footer` ids are legacy; the ticket's class names (`.main`, `.footer`) are used (ids not required).
- `todomvc-app-css` / `todomvc-common` cannot be fetched from npm necessarily (offline); the CSS is authored/vendored locally in `css/` reproducing the official look (from the spec of the look: Helvetica, #f5f5f5 bg, red "todos" title, card layout, checkbox SVG ticks). `todomvc-common` is listed as a dependency but not used at runtime.
- Storage key `todos-vanillajs`. IDs are unique strings/numbers generated locally.
- Playwright available globally (v1.63); package.json pins `@playwright/test` as devDependency; tests use the system browsers if the bundled ones are missing (config allows `PLAYWRIGHT_CHROMIUM_EXECUTABLE`).
- `serve` is a Node script (no deps) serving static files with correct MIME types incl. ES modules, restricted to the project root's public files.

## Test strategy
- Playwright e2e (tests/e2e/*.spec.js) covering R2–R16 one-by-one: structure, empty state, add/trim/empty, toggle, toggle-all, edit (enter/blur/escape/empty), destroy hover/click, counter plurality (0/1/2), clear completed, persistence incl. reload and corrupt storage, routing incl. selected class, filtered updates, back button, reload keeps filter, XSS escaping, insertion order.
- Serve test: starting `./serve --port` and fetching `/` and module MIME type (via Playwright webServer + request fixture).
