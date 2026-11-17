const ENTER_KEY = 'Enter';
const ESCAPE_KEY = 'Escape';

export function parseFilter(hash) {
  const path = hash.replace(/^#!?/, '');
  if (path === '/active') {
    return 'active';
  }
  if (path === '/completed') {
    return 'completed';
  }
  return 'all';
}

export class TodosController {
  constructor(model, view, win) {
    this.model = model;
    this.view = view;
    this.win = win;
    this.filter = parseFilter(win.location.hash);
    model.subscribe(() => this.render());
    this.bind();
    this.render();
  }

  render() {
    this.view.render(this.model, this.filter);
  }

  bind() {
    const { view, model } = this;
    view.input.addEventListener('keydown', (e) => {
      if (e.key === ENTER_KEY) {
        const title = view.input.value;
        view.input.value = '';
        model.add(title);
      }
    });
    view.toggleAll.addEventListener('change', () => model.toggleAll(view.toggleAll.checked));
    view.clear.addEventListener('click', () => model.clearCompleted());
    this.win.addEventListener('hashchange', () => {
      this.filter = parseFilter(this.win.location.hash);
      this.view.editingId = null;
      this.render();
    });

    const idOf = (el) => el.closest('li').dataset.id;
    view.list.addEventListener('change', (e) => {
      if (e.target.classList.contains('toggle')) {
        model.setCompleted(idOf(e.target), e.target.checked);
      }
    });
    view.list.addEventListener('click', (e) => {
      if (e.target.classList.contains('destroy')) {
        model.remove(idOf(e.target));
      }
    });
    view.list.addEventListener('dblclick', (e) => {
      if (e.target.tagName === 'LABEL') {
        view.editingId = idOf(e.target);
        this.render();
      }
    });
    view.list.addEventListener('keydown', (e) => {
      if (!e.target.classList.contains('edit')) {
        return;
      }
      if (e.key === ENTER_KEY) {
        this.finishEdit(e.target, true);
      } else if (e.key === ESCAPE_KEY) {
        this.finishEdit(e.target, false);
      }
    });
    view.list.addEventListener('focusout', (e) => {
      if (e.target.classList.contains('edit')) {
        this.finishEdit(e.target, true);
      }
    });
  }

  finishEdit(input, save) {
    const li = input.closest('li');
    if (!li || this.view.editingId !== li.dataset.id) {
      return; // already finished (e.g. Escape followed by blur)
    }
    const id = li.dataset.id;
    this.view.editingId = null;
    const todo = this.model.todos.find((t) => t.id === id);
    if (!save || (todo && input.value.trim() === todo.title)) {
      // Nothing to persist: leave edit mode in place without re-rendering, so a click
      // that caused this blur still reaches its target element.
      li.classList.remove('editing');
      input.remove();
      return;
    }
    this.model.update(id, input.value);
  }
}
