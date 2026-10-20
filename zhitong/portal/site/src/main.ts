import { createApp, createSSRApp } from 'vue';
import App from './App.vue';
import './styles/index.css';

const root = document.getElementById('app')!;
const app = root.firstElementChild ? createSSRApp(App) : createApp(App);
app.mount(root);
