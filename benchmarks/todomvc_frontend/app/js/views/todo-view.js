export class TodoView {
  constructor(root) {
    this.root = root;
    this.input = root.querySelector('.new-todo');
    this.main = root.querySelector('.main');
    this.toggleAll = root.querySelector('.toggle-all');
    this.list = root.querySelector('.todo-list');
    this.footer = root.querySelector('.footer');
    this.count = root.querySelector('.todo-count');
    this.links = Array.from(root.querySelectorAll('.filters a'));
    this.clear = root.querySelector('.clear-completed');
    this.editingId = null;
  }

  render(model, filter) {
    const total = model.todos.length;
    const active = model.activeCount;
    this.main.hidden = total === 0;
    this.footer.hidden = total === 0;
    this.toggleAll.checked = total > 0 && active === 0;
    this.renderList(model.filtered(filter));
    this.count.replaceChildren();
    const strong = document.createElement('strong');
    strong.textContent = String(active);
    this.count.append(strong, active === 1 ? ' item left' : ' items left');
    this.clear.hidden = model.completedCount === 0;
    this.links.forEach((a) => {
      const href = a.getAttribute('href');
      const name = href === '#/' ? 'all' : href.slice(2);
      a.classList.toggle('selected', name === filter);
    });
  }

  renderList(todos) {
    const items = todos.map((todo) => this.renderItem(todo));
    this.list.replaceChildren(...items);
    const edit = this.list.querySelector('li.editing .edit');
    if (edit) {
      edit.focus();
      edit.setSelectionRange(edit.value.length, edit.value.length);
    }
  }

  renderItem(todo) {
    const li = document.createElement('li');
    li.dataset.id = todo.id;
    li.classList.toggle('completed', todo.completed);
    const view = document.createElement('div');
    view.className = 'view';
    const toggle = document.createElement('input');
    toggle.className = 'toggle';
    toggle.type = 'checkbox';
    toggle.checked = todo.completed;
    const label = document.createElement('label');
    label.textContent = todo.title;
    const destroy = document.createElement('button');
    destroy.className = 'destroy';
    view.append(toggle, label, destroy);
    li.append(view);
    if (this.editingId === todo.id) {
      li.classList.add('editing');
      const edit = document.createElement('input');
      edit.className = 'edit';
      edit.value = todo.title;
      li.append(edit);
    }
    return li;
  }
}
