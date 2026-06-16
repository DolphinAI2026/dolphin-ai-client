"""account-service 管理后台单页 (self-contained, Vue 3 + axios CDN)。

公网经 ingress 挂在 /account-api 下, 页面本身在 /account-api/admin-ui;
因此页内所有 API 调用都走相对前缀 const API='/account-api'。
"""

ADMIN_UI_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>桌面账号管理</title>
<style>
  body { font-family: -apple-system, "Segoe UI", system-ui, sans-serif; margin: 0; background: #f5f6f8; color: #222; }
  #app { max-width: 880px; margin: 0 auto; padding: 24px 16px 64px; }
  h1 { font-size: 20px; margin: 0 0 16px; }
  h2 { font-size: 15px; margin: 24px 0 8px; color: #555; }
  .card { background: #fff; border: 1px solid #e3e5e8; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
  input { padding: 7px 9px; border: 1px solid #cbd0d6; border-radius: 5px; font-size: 14px; }
  button { padding: 7px 12px; border: 1px solid #2c6cd6; background: #2c6cd6; color: #fff;
           border-radius: 5px; font-size: 13px; cursor: pointer; }
  button.ghost { background: #fff; color: #2c6cd6; }
  button.danger { background: #fff; color: #c0392b; border-color: #c0392b; }
  button:disabled { opacity: .55; cursor: default; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #eee; }
  th { color: #777; font-weight: 600; font-size: 12px; }
  .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .muted { color: #999; }
  .tag { display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 12px; }
  .tag.on { background: #e6f4ea; color: #1e7e34; }
  .tag.off { background: #fdecea; color: #c0392b; }
  .tag.admin { background: #eef2fb; color: #2c6cd6; }
  .who { float: right; font-size: 13px; color: #666; }
</style>
</head>
<body>
<div id="app">
  <h1>桌面账号管理
    <span class="who" v-if="token">
      {{ me }} · <a href="#" @click.prevent="logout">退出</a>
    </span>
  </h1>

  <!-- 登录 -->
  <div class="card" v-if="!token">
    <h2 style="margin-top:0">登录</h2>
    <div class="row">
      <input v-model="loginForm.username" placeholder="用户名" @keyup.enter="login" />
      <input v-model="loginForm.password" type="password" placeholder="密码" @keyup.enter="login" />
      <button :disabled="busy" @click="login">登录</button>
    </div>
  </div>

  <!-- 已登录 -->
  <div v-if="token">
    <!-- 新增 -->
    <div class="card">
      <h2 style="margin-top:0">新增账号</h2>
      <div class="row">
        <input v-model="createForm.username" placeholder="用户名" />
        <input v-model="createForm.password" type="password" placeholder="密码 (至少 8 位)" />
        <button :disabled="busy" @click="createAccount">创建</button>
      </div>
    </div>

    <!-- 列表 -->
    <div class="card">
      <h2 style="margin-top:0">
        账号列表
        <button class="ghost" style="float:right" :disabled="busy" @click="loadAccounts">刷新</button>
      </h2>
      <table>
        <thead>
          <tr><th>ID</th><th>用户名</th><th>租户</th><th>状态</th><th>角色</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="a in accounts" :key="a.id">
            <td class="muted">{{ a.id }}</td>
            <td>{{ a.username }}</td>
            <td class="muted">{{ a.tenant_id == null ? '—' : a.tenant_id }}</td>
            <td>
              <span class="tag" :class="a.is_active ? 'on' : 'off'">
                {{ a.is_active ? '启用' : '停用' }}
              </span>
            </td>
            <td>
              <span class="tag admin" v-if="a.is_platform_admin">管理员</span>
              <span class="muted" v-else>普通</span>
            </td>
            <td class="row">
              <button v-if="a.is_active" class="danger" :disabled="busy"
                      @click="patch(a, 'disable')">停用</button>
              <button v-else class="ghost" :disabled="busy"
                      @click="patch(a, 'enable')">启用</button>
              <button class="ghost" :disabled="busy" @click="resetPassword(a)">改密</button>
            </td>
          </tr>
          <tr v-if="!accounts.length">
            <td colspan="6" class="muted" style="text-align:center;padding:24px">暂无账号</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</div>

<script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
<script src="https://unpkg.com/axios/dist/axios.min.js"></script>
<script>
const API = '/account-api';
const { createApp } = Vue;

createApp({
  data() {
    return {
      token: '',
      me: '',
      busy: false,
      loginForm: { username: '', password: '' },
      createForm: { username: '', password: '' },
      accounts: [],
    };
  },
  computed: {
    authHeaders() {
      return this.token ? { Authorization: 'Bearer ' + this.token } : {};
    },
  },
  methods: {
    err(e) {
      const d = e && e.response && e.response.data && (e.response.data.detail || e.response.data.message);
      alert(d || (e && e.message) || '请求失败');
    },
    async login() {
      if (!this.loginForm.username || !this.loginForm.password) { alert('请输入用户名和密码'); return; }
      this.busy = true;
      try {
        const r = await axios.post(API + '/api/desktop-auth/login', {
          username: this.loginForm.username, password: this.loginForm.password,
        });
        this.token = r.data.access_token;
        this.me = r.data.username;
        this.loginForm.password = '';
        await this.loadAccounts();
      } catch (e) { this.err(e); }
      finally { this.busy = false; }
    },
    logout() { this.token = ''; this.me = ''; this.accounts = []; },
    async loadAccounts() {
      this.busy = true;
      try {
        const r = await axios.get(API + '/api/desktop-auth/admin/accounts', { headers: this.authHeaders });
        this.accounts = r.data;
      } catch (e) { this.err(e); }
      finally { this.busy = false; }
    },
    async createAccount() {
      if (!this.createForm.username || !this.createForm.password) { alert('请输入用户名和密码'); return; }
      if (this.createForm.password.length < 8) { alert('密码至少 8 位'); return; }
      this.busy = true;
      try {
        await axios.post(API + '/api/desktop-auth/admin/accounts', {
          username: this.createForm.username, password: this.createForm.password,
        }, { headers: this.authHeaders });
        this.createForm = { username: '', password: '' };
        await this.loadAccounts();
      } catch (e) { this.err(e); }
      finally { this.busy = false; }
    },
    async patch(a, action) {
      this.busy = true;
      try {
        await axios.patch(API + '/api/desktop-auth/admin/accounts/' + encodeURIComponent(a.username),
          { action }, { headers: this.authHeaders });
        await this.loadAccounts();
      } catch (e) { this.err(e); }
      finally { this.busy = false; }
    },
    async resetPassword(a) {
      const pw = prompt('为 ' + a.username + ' 设置新密码 (至少 8 位):');
      if (pw == null) return;
      if (pw.length < 8) { alert('密码至少 8 位'); return; }
      this.busy = true;
      try {
        await axios.patch(API + '/api/desktop-auth/admin/accounts/' + encodeURIComponent(a.username),
          { action: 'reset_password', password: pw }, { headers: this.authHeaders });
        alert('已更新密码');
      } catch (e) { this.err(e); }
      finally { this.busy = false; }
    },
  },
}).mount('#app');
</script>
</body>
</html>
"""
