import Vue from 'vue'
import App from './App.vue'

Vue.config.productionTip = false
import './style.sass';
import './shards.scss';

new Vue({
  render: h => h(App),
}).$mount('#app')
