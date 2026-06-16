"""account-service 管理后台单页 (self-contained, Vue 3 + Element Plus CDN)。
企业级后台风: 克制配色 (navy/slate)、Lexend 字体、Element Plus 组件。GET /admin-ui 返回。
页面经 ingress 挂在 /account-api 下, API 走相对前缀 const API='/account-api'。
"""

ADMIN_UI_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>桌面账号管理</title>
<link rel="stylesheet" href="https://unpkg.com/element-plus/dist/index.css">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Lexend:wght@400;500;600;700&display=swap');
  :root{
    --bg:#f3f5f9; --surface:#ffffff; --border:#e6e9f0;
    --text:#1b2433; --text-muted:#5a6678; --brand:#2563eb; --brand-deep:#1e3a8a;
  }
  *{box-sizing:border-box}
  html,body{margin:0;padding:0}
  body{
    font-family:'Lexend',-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;
    background:var(--bg); color:var(--text); -webkit-font-smoothing:antialiased;
  }
  .el-button{font-family:inherit}

  /* 登录 */
  .login-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center;
    background:radial-gradient(1200px 600px at 50% -10%, #eaf0fb 0%, var(--bg) 60%);}
  .login-card{width:392px;background:var(--surface);border:1px solid var(--border);
    border-radius:16px;padding:38px 36px;box-shadow:0 10px 40px rgba(20,34,62,.08);}
  .login-head{display:flex;flex-direction:column;align-items:center;gap:12px;margin-bottom:26px}
  .mark{width:46px;height:46px;border-radius:12px;display:flex;align-items:center;justify-content:center;
    background:linear-gradient(135deg,var(--brand) 0%,var(--brand-deep) 100%);
    box-shadow:0 6px 16px rgba(37,99,235,.28);}
  .mark svg{width:24px;height:24px;color:#fff}
  .login-title{font-size:19px;font-weight:600;letter-spacing:.3px}
  .login-sub{font-size:13px;color:var(--text-muted);margin-top:-4px}
  .login-card .el-input{margin-bottom:16px}

  /* 顶栏 */
  .topbar{height:62px;background:var(--surface);border-bottom:1px solid var(--border);
    display:flex;align-items:center;justify-content:space-between;padding:0 28px;
    position:sticky;top:0;z-index:10}
  .brand{display:flex;align-items:center;gap:12px;font-size:16px;font-weight:600}
  .brand .mark{width:34px;height:34px;border-radius:9px;box-shadow:0 4px 10px rgba(37,99,235,.25)}
  .brand .mark svg{width:18px;height:18px}
  .topbar-right{display:flex;align-items:center;gap:14px;font-size:14px;color:var(--text-muted)}
  .who{display:flex;align-items:center;gap:7px}
  .avatar{width:26px;height:26px;border-radius:50%;background:#e7edfb;color:var(--brand);
    font-size:12px;font-weight:600;display:flex;align-items:center;justify-content:center}

  /* 内容 */
  .container{max-width:1060px;margin:26px auto 60px;padding:0 24px}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:14px;
    padding:22px 24px;margin-bottom:20px}
  .card-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}
  .card-title{font-size:15px;font-weight:600;display:flex;align-items:center;gap:9px}
  .card-title .dot{width:7px;height:7px;border-radius:2px;background:var(--brand)}
  .hint{font-size:12px;color:var(--text-muted)}
  .create-row{display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap}
  .create-row .el-input{width:220px}
  .el-table{--el-table-header-bg-color:#f7f9fc;border-radius:10px}
  .el-table th .cell{color:var(--text-muted);font-weight:600;font-size:13px}
  .muted{color:var(--text-muted)}
  @media (max-width:560px){.create-row .el-input{width:100%}}
</style>
</head>
<body>
<div id="app">
  <!-- 登录 -->
  <div v-if="!token" class="login-wrap">
    <div class="login-card">
      <div class="login-head">
        <div class="mark"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></div>
        <div class="login-title">桌面账号管理</div>
        <div class="login-sub">account-service · 管理员登录</div>
      </div>
      <el-input v-model="loginForm.username" placeholder="用户名" size="large" clearable @keyup.enter="login"></el-input>
      <el-input v-model="loginForm.password" type="password" placeholder="密码" size="large" show-password @keyup.enter="login"></el-input>
      <el-button type="primary" size="large" style="width:100%;margin-top:4px" :loading="loggingIn" @click="login">登录</el-button>
    </div>
  </div>

  <!-- 主界面 -->
  <template v-else>
    <div class="topbar">
      <div class="brand">
        <div class="mark"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></div>
        桌面账号管理
      </div>
      <div class="topbar-right">
        <span class="who"><span class="avatar">{{ (me||'?').slice(0,1).toUpperCase() }}</span>{{ me }}</span>
        <el-button text @click="logout">退出</el-button>
      </div>
    </div>

    <div class="container">
      <!-- 新增账号 -->
      <div class="card">
        <div class="card-head">
          <div class="card-title"><span class="dot"></span>新增账号</div>
          <span class="hint">新账号自带独立租户, 作为该租户管理员</span>
        </div>
        <div class="create-row">
          <el-input v-model="createForm.username" placeholder="用户名" clearable></el-input>
          <el-input v-model="createForm.password" type="password" placeholder="密码(至少 8 位)" show-password clearable @keyup.enter="createAccount"></el-input>
          <el-button type="primary" :loading="creating" @click="createAccount">创建</el-button>
        </div>
      </div>

      <!-- 账号列表 -->
      <div class="card">
        <div class="card-head">
          <div class="card-title"><span class="dot"></span>账号列表 <span class="muted" style="font-weight:400;font-size:13px">· {{ accounts.length }} 个</span></div>
          <el-button :icon="RefreshIcon" :loading="loading" @click="loadAccounts" plain size="small">刷新</el-button>
        </div>
        <el-table :data="accounts" v-loading="loading" stripe style="width:100%">
          <el-table-column prop="id" label="ID" width="72"></el-table-column>
          <el-table-column label="用户名" min-width="160">
            <template #default="s"><span style="font-weight:500">{{ s.row.username }}</span></template>
          </el-table-column>
          <el-table-column label="租户" width="100">
            <template #default="s"><span class="muted">#{{ s.row.tenant_id ?? '-' }}</span></template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="s">
              <el-tag :type="s.row.is_active ? 'success' : 'info'" effect="light" round size="small">{{ s.row.is_active ? '启用' : '已停用' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="角色" width="120">
            <template #default="s">
              <el-tag v-if="s.row.is_platform_admin" type="primary" effect="plain" size="small">管理员</el-tag>
              <span v-else class="muted">普通</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" min-width="190">
            <template #default="s">
              <el-button v-if="s.row.is_active" text type="danger" size="small" @click="setActive(s.row,false)">停用</el-button>
              <el-button v-else text type="success" size="small" @click="setActive(s.row,true)">启用</el-button>
              <el-button text type="primary" size="small" @click="resetPwd(s.row)">改密</el-button>
            </template>
          </el-table-column>
          <template #empty><span class="muted">暂无账号</span></template>
        </el-table>
      </div>
    </div>
  </template>
</div>

<script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
<script src="https://unpkg.com/element-plus"></script>
<script src="https://unpkg.com/@element-plus/icons-vue"></script>
<script src="https://unpkg.com/axios/dist/axios.min.js"></script>
<script>
const { createApp, ref, reactive } = Vue
const { ElMessage, ElMessageBox } = ElementPlus
const API = '/account-api'

const app = createApp({
  setup(){
    const token = ref('')
    const me = ref('')
    const loginForm = reactive({ username:'', password:'' })
    const createForm = reactive({ username:'', password:'' })
    const accounts = ref([])
    const loggingIn = ref(false), creating = ref(false), loading = ref(false)
    const RefreshIcon = (window.ElementPlusIconsVue || {}).Refresh

    const auth = () => ({ headers:{ Authorization:'Bearer '+token.value } })
    const err = (e, fb) => ElMessage.error((e && e.response && e.response.data && e.response.data.detail) || fb)

    async function login(){
      if(!loginForm.username || !loginForm.password) return ElMessage.warning('请输入用户名和密码')
      loggingIn.value = true
      try{
        const { data } = await axios.post(API+'/api/desktop-auth/login', { username:loginForm.username, password:loginForm.password })
        token.value = data.access_token; me.value = data.username
        loginForm.password = ''
        await loadAccounts()
      }catch(e){ err(e,'登录失败') }
      finally{ loggingIn.value = false }
    }
    function logout(){ token.value=''; me.value=''; accounts.value=[] }

    async function loadAccounts(){
      loading.value = true
      try{ const { data } = await axios.get(API+'/api/desktop-auth/admin/accounts', auth()); accounts.value = data }
      catch(e){ err(e,'加载失败') }
      finally{ loading.value = false }
    }

    async function createAccount(){
      if(!createForm.username) return ElMessage.warning('请输入用户名')
      if((createForm.password||'').length < 8) return ElMessage.warning('密码至少 8 位')
      creating.value = true
      try{
        await axios.post(API+'/api/desktop-auth/admin/accounts', { username:createForm.username, password:createForm.password }, auth())
        ElMessage.success('已创建 '+createForm.username)
        createForm.username=''; createForm.password=''
        await loadAccounts()
      }catch(e){ err(e,'创建失败') }
      finally{ creating.value = false }
    }

    async function setActive(row, active){
      try{
        await ElMessageBox.confirm('确定'+(active?'启用':'停用')+'账号 '+row.username+' ?', '确认', { type: active?'info':'warning', confirmButtonText:'确定', cancelButtonText:'取消' })
      }catch(_){ return }
      try{
        await axios.patch(API+'/api/desktop-auth/admin/accounts/'+encodeURIComponent(row.username), { action: active?'enable':'disable' }, auth())
        ElMessage.success((active?'已启用 ':'已停用 ')+row.username)
        await loadAccounts()
      }catch(e){ err(e,'操作失败') }
    }

    async function resetPwd(row){
      let pwd
      try{
        const r = await ElMessageBox.prompt('给 '+row.username+' 设置新密码(至少 8 位)', '改密', {
          confirmButtonText:'确定', cancelButtonText:'取消', inputType:'password',
          inputValidator:(v)=> (v && v.length>=8) || '密码至少 8 位'
        })
        pwd = r.value
      }catch(_){ return }
      try{
        await axios.patch(API+'/api/desktop-auth/admin/accounts/'+encodeURIComponent(row.username), { action:'reset_password', password:pwd }, auth())
        ElMessage.success('已重置 '+row.username+' 的密码')
      }catch(e){ err(e,'改密失败') }
    }

    return { token, me, loginForm, createForm, accounts, loggingIn, creating, loading, RefreshIcon,
             login, logout, loadAccounts, createAccount, setActive, resetPwd }
  }
})
app.use(ElementPlus)
app.mount('#app')
</script>
</body>
</html>
"""
