import { createRouter, createWebHistory } from 'vue-router'
import SettingsView from './views/SettingsView.vue'
import SessionsView from './views/SessionsView.vue'
import ChatView from './views/ChatView.vue'
import PlaceholderView from './views/PlaceholderView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/sessions' },
    { path: '/settings', name: 'settings', component: SettingsView },
    { path: '/sessions', name: 'sessions', component: SessionsView },
    { path: '/chat', name: 'chat', component: ChatView },
    {
      path: '/workflows',
      name: 'workflows',
      component: PlaceholderView,
      props: { title: '工作流', milestone: 'M2' },
    },
  ],
})