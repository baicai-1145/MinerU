import { createApp } from 'vue';
import { createPinia } from 'pinia';

import App from './App.vue';
import './styles/theme.css';
import { loadConfig } from './config';

async function bootstrap() {
  await loadConfig();
  const app = createApp(App);
  app.use(createPinia());
  app.mount('#app');
}

bootstrap();
