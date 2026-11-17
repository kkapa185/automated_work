export const STORAGE_KEY = 'todos-vanillajs';

export class TodoModel {
  constructor(storage) {
    this.storage = storage;
    this.todos = this.load();
    this.listeners = [];
  }

  load() {
    try {
      const data = JSON.parse(this.storage.getItem(STORAGE_KEY));
      if (!Array.isArray(data)) {
        return [];
      }
      return data
        .filter((t) => t && typeof t.title === 'string')
        .map((t) => ({ id: String(t.id), title: t.title, completed: t.completed === true }));
    } catch (e) {
      return [];
    }
  }

  save() {
    try {
      this.storage.setItem(STORAGE_KEY, JSON.stringify(this.todos));
    } catch (e) {
      // storage unavailable or full: keep working in memory
    }
  }

  subscribe(fn) {
    this.listeners.push(fn);
  }

  commit() {
    this.save();
    this.listeners.forEach((fn) => fn());
  }

  nextId() {
    const used = new Set(this.todos.map((t) => t.id));
    let id;
    do {
      id = Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    } while (used.has(id));
    return id;
  }

  add(title) {
    const trimmed = title.trim();
    if (!trimmed) {
      return;
    }
    this.todos.push({ id: this.nextId(), title: trimmed, completed: false });
    this.commit();
  }

  update(id, title) {
    const trimmed = title.trim();
    if (!trimmed) {
      this.remove(id);
      return;
    }
    const todo = this.todos.find((t) => t.id === id);
    if (todo) {
      todo.title = trimmed;
      this.commit();
    }
  }

  setCompleted(id, completed) {
    const todo = this.todos.find((t) => t.id === id);
    if (todo) {
      todo.completed = completed;
      this.commit();
    }
  }

  toggleAll(completed) {
    this.todos.forEach((t) => {
      t.completed = completed;
    });
    this.commit();
  }

  remove(id) {
    this.todos = this.todos.filter((t) => t.id !== id);
    this.commit();
  }

  clearCompleted() {
    this.todos = this.todos.filter((t) => !t.completed);
    this.commit();
  }

  filtered(filter) {
    if (filter === 'active') {
      return this.todos.filter((t) => !t.completed);
    }
    if (filter === 'completed') {
      return this.todos.filter((t) => t.completed);
    }
    return this.todos.slice();
  }

  get activeCount() {
    return this.todos.filter((t) => !t.completed).length;
  }

  get completedCount() {
    return this.todos.length - this.activeCount;
  }
}
