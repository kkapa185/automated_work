import { TodoModel } from './models/todo-model.js';
import { TodoView } from './views/todo-view.js';
import { TodosController } from './controllers/todos.js';

const model = new TodoModel(window.localStorage);
const view = new TodoView(document.querySelector('.todoapp'));
new TodosController(model, view, window);
