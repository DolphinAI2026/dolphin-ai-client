"use strict";var de=Object.create;var W=Object.defineProperty;var pe=Object.getOwnPropertyDescriptor;var fe=Object.getOwnPropertyNames;var ue=Object.getPrototypeOf,he=Object.prototype.hasOwnProperty;var me=(d,e)=>{for(var t in e)W(d,t,{get:e[t],enumerable:!0})},ee=(d,e,t,n)=>{if(e&&typeof e=="object"||typeof e=="function")for(let s of fe(e))!he.call(d,s)&&s!==t&&W(d,s,{get:()=>e[s],enumerable:!(n=pe(e,s))||n.enumerable});return d};var F=(d,e,t)=>(t=d!=null?de(ue(d)):{},ee(e||!d||!d.__esModule?W(t,"default",{value:d,enumerable:!0}):t,d)),ge=d=>ee(W({},"__esModule",{value:!0}),d);var We={};me(We,{activate:()=>Oe,deactivate:()=>Ne});module.exports=ge(We);var Y=F(require("vscode"));var b=F(require("vscode"));function ve(d){return d.replace(/<think>[\s\S]*?<\/think>/gi,"")}function we(d){return d.replace(/\[?\/?TOOL_CALL\]/gi,"").replace(/<minimax:tool_call>[\s\S]*?<\/minimax:tool_call>/gi,"").replace(/minimax:tool_call/gi,"").replace(/<\/?invoke[^>]*>/gi,"").replace(/\{"tool"\s*[=:>]+\s*"[^"]*"\s*,\s*"path"\s*[=:>]+\s*"[^"]*"\s*\}/g,"")}function O(d){return we(ve(d)).replace(/^\s*[\r\n]+/gm,"").trim()}var D=class d{buffer="";inTag=!1;tagType=null;static OPEN_PATTERNS=[{open:"<think>",close:"</think>",type:"think"},{open:"<minimax:tool_call>",close:"</minimax:tool_call>",type:"toolcall"}];push(e){this.buffer+=e;let t="";for(;this.buffer.length>0;){if(this.inTag&&this.tagType){let i=d.OPEN_PATTERNS.find(f=>f.type===this.tagType)?.close||"",o=this.buffer.indexOf(i);if(o===-1){this.buffer.length>1e4&&(this.buffer="",this.inTag=!1,this.tagType=null);break}this.buffer=this.buffer.slice(o+i.length),this.inTag=!1,this.tagType=null;continue}let n=-1,s=null;for(let i of d.OPEN_PATTERNS){let o=this.buffer.indexOf(i.open);o!==-1&&(n===-1||o<n)&&(n=o,s=i)}if(n===-1){let i=Math.max(0,this.buffer.length-30);t+=this.buffer.slice(0,i),this.buffer=this.buffer.slice(i);break}t+=this.buffer.slice(0,n),this.buffer=this.buffer.slice(n+s.open.length),this.inTag=!0,this.tagType=s.type}return t}flush(){let e=this.buffer;return this.buffer="",this.inTag=!1,this.tagType=null,this.inTag?"":e}};function te(d){let e=d.match(/[A-Za-z0-9_\-./]+\.\w{1,8}/g)||[];return[...new Set(e)].filter(t=>!t.startsWith("http")&&t.includes("/")||t.includes("."))}function Z(d){return/(修改|修复|改一下|改下|调整|fix|bug|创建|新增|开发|实现|搭建|编写|生成|写一个|写个|帮我写|做一个|做个|build|create|implement|develop|delete|删除|去掉|加上|加个|添加|增加|替换|改成|改为|加注释|写注释|加comment|重构|refactor|优化|整理|格式化|补充|完善|更新|升级|迁移|移动|重命名|rename|注释|comment|加一下|改一下|写一下|补一下)/i.test(d)}function ne(d){return/^(确认|应用|apply|yes|ok|接受|accept|好的|行|可以|没问题|开始|go|start|开始吧|开干|冲)/i.test(d.trim())}function ie(d){return/^(取消|拒绝|cancel|no|reject|算了|不要|不用了)/i.test(d.trim())}var B=class{constructor(e){this.config=e}async*stream(e){let{model:t,messages:n,maxTokens:s=4096,token:i}=e,o=this.config.getEndpoint("/chat/completions"),f=this.config.getHeaders(),c=JSON.stringify({model:t,messages:n,stream:!0,max_tokens:s,tool_choice:"none"}),a=new AbortController;i?.onCancellationRequested(()=>a.abort());let r=setTimeout(()=>a.abort(),12e4),p;try{p=await fetch(o,{method:"POST",headers:f,body:c,signal:a.signal})}catch(C){if(clearTimeout(r),C.name==="AbortError")return"";throw new Error(`LLM request failed: ${C.message}`)}if(clearTimeout(r),!p.ok){let C="";try{C=(await p.text()).slice(0,300)}catch{}throw new Error(`LLM API ${p.status}: ${C}`)}let l=p.body?.getReader();if(!l)try{let m=(await p.json())?.choices?.[0]?.message?.content||"";return yield m,m}catch{return""}let h=new TextDecoder,x=new D,S="",k="",w=Date.now(),v=(e.maxTokens??0)>4e3?45e3:(e.maxTokens??0)<500?15e3:3e4;try{for(;!i?.isCancellationRequested;){let C=Date.now()-w,m=Math.max(5e3,v-C),P=new Promise(T=>setTimeout(()=>T({done:!0,timeout:!0}),m)),$=l.read(),M=await Promise.race([$,P]);if(M.timeout||M.done){M.done||(k+=h.decode());break}w=Date.now(),k+=h.decode(M.value,{stream:!0});let u=k.split(`
`);k=u.pop()||"";for(let T of u){if(!T.startsWith("data: "))continue;let y=T.slice(6).trim();if(!(!y||y==="[DONE]"))try{let L=JSON.parse(y)?.choices?.[0]?.delta?.content;if(L){let A=x.push(L);A&&(S+=A,yield A)}}catch{}}}}finally{try{l.cancel()}catch{}}let E=x.flush();return E&&(S+=E,yield E),S}async complete(e){let t="";for await(let n of this.stream(e))t+=n;return t}async*streamCodingPipeline(e){let{message:t,selectedModel:n,conversationId:s,projectId:i,projectType:o,token:f}=e,c=this.config.getHarnessEndpoint("/pipeline"),a=this.config.getHeaders(),r=JSON.stringify({message:t,selected_model:n||void 0,conversation_id:s??this.config.get().conversationId??void 0,project_id:i??void 0,project_type:o??void 0}),p=new AbortController;f?.onCancellationRequested(()=>p.abort());let l=setTimeout(()=>p.abort(),3e5),h;try{h=await fetch(c,{method:"POST",headers:a,body:r,signal:p.signal})}catch(w){if(clearTimeout(l),w.name==="AbortError")return;throw new Error(`Coding pipeline request failed: ${w.message}`)}if(clearTimeout(l),!h.ok){let w="";try{w=(await h.text()).slice(0,500)}catch{}throw new Error(`Coding pipeline ${h.status}: ${w}`)}let x=h.body?.getReader();if(!x)return;let S=new TextDecoder,k="";try{for(;!f?.isCancellationRequested;){let w=await x.read();if(w.done)break;k+=S.decode(w.value,{stream:!0});let v=k.split(`

`);k=v.pop()||"";for(let E of v){let C=E.split(`
`),m="message",P=[];for(let M of C)M.startsWith("event:")?m=M.slice(6).trim():M.startsWith("data:")&&P.push(M.slice(5).trim());if(m==="ping")continue;let $=P.join(`
`).trim();if(!(!$||$==="[DONE]"))try{yield JSON.parse($)}catch{}}}}finally{try{x.cancel()}catch{}}}async fetchModels(){try{let e=this.config.getEndpoint("/models"),t=await fetch(e,{headers:this.config.getHeaders()});if(!t.ok)return[];let n=await t.json();return n?.models||n?.data||[]}catch{return[]}}};var _=F(require("vscode"));var ye="**/node_modules/**,**/dist/**,**/.git/**,**/*.zip,**/*.jar,**/*.war,**/target/**,**/build/**,**/.idea/**",xe=2600,ke=9e3,se=6e3,Ce=24,_e=48e3,Ee=3.5,Te=60,be=3e5,oe=/\.(vue|js|jsx|ts|tsx|json|java|xml|yml|yaml|properties|scss|css|less|html)$/i,Se=/(国际化|i18n|多语言|语言包|locale|翻译|文案)/i,Pe=/(组件|widget|表单组件|form-component|render|渲染|upload|avatar|date|picker)/i,Me=/(componentModelField|配置文件|配置项|config|widget\.config|editor\.config|字段类型|数据模型|STRING|DATE|字段绑定)/i,$e=/(检查|排查|看看|看一下|看一看|存不存在|缺失|缺少|不存在|有没有|是否存在|注册|入口|导入|导出|import|export|index\.js)/i,Le=new Set(["src","form","component","widget","config","file","path","this","that","date","range","string","model","field","type","please","help","code"]),H=class{cache=null;dirty=!1;config=null;setConfig(e){this.config=e}markDirty(){this.dirty=!0}async build(e){let t=_.workspace.workspaceFolders;if(!t?.length)return"";let n=te(e),s=this._buildCacheKey(n,e);if(this.cache&&!this.dirty&&this.cache.key===s&&Date.now()-this.cache.ts<be)return this.cache.text;try{let i=await this._buildContext(t[0],n,e);return this.cache={key:s,text:i,ts:Date.now()},this.dirty=!1,i}catch(i){return console.warn("[RuijingAI] contextBuilder failed",i),""}}async _buildContext(e,t,n){let i=(await _.workspace.findFiles(new _.RelativePattern(e,"**/*"),`{${ye}}`,500)).map(u=>_.workspace.asRelativePath(u,!1)).sort(),o=Se.test(n),f=Pe.test(n),c=Me.test(n),a=$e.test(n),r=_.window.visibleTextEditors.map(u=>_.workspace.asRelativePath(u.document.uri,!1)).filter(u=>!!u&&oe.test(u)&&!u.startsWith(".cursor/rules/")&&!u.startsWith(".claude/rules/")&&!/\.(md|mdc|txt)$/i.test(u)),p=this._extractSearchTerms(n,t,r),l=[],h=u=>{u&&!l.includes(u)&&l.push(u)};for(let u of t)for(let T of this._expandMentionedPathCandidates(u)){let y=i.filter(g=>g.endsWith(T)||g.includes(T));for(let g of y.slice(0,4))h(g)}let x=i.filter(u=>oe.test(u)).map(u=>({rel:u,score:this._scorePath(u,p,{activeSourceFiles:r,isConfigTask:c,isI18nTask:o,isFormComponentTask:f})})).filter(u=>u.score>0).sort((u,T)=>T.score-u.score||u.rel.localeCompare(T.rel));for(let u of x.slice(0,12))h(u.rel);for(let u of r)h(u);if(i.includes("src/apaas.json")){let u=["src/apaas.json","src/index.js","src/form-component/form-widget/index.js","src/form-component/form-editor/index.js","src/form-component/index.js","src/form-component-config/form-widget/index.js","src/form-component-config/form-editor/index.js","src/form-component-config/index.js"];for(let y of i)(y.endsWith(".widget.config.js")||y.endsWith(".editor.config.js"))&&(u.includes(y)||u.push(y));let T=u.filter(y=>i.includes(y)).sort((y,g)=>this._scorePath(g,p,{activeSourceFiles:r,isConfigTask:c,isI18nTask:o,isFormComponentTask:f})-this._scorePath(y,p,{activeSourceFiles:r,isConfigTask:c,isI18nTask:o,isFormComponentTask:f}));for(let y of T)h(y);if(o){let y=["src/form-component-local/index.js","src/form-component-local/zh-CN/index.js","src/form-component-local/en-US/index.js"];for(let g of y)i.includes(g)&&h(g)}if(a){let y=i.filter(g=>(g.endsWith("/index.js")||g.endsWith("/index.ts"))&&(g.includes("form-component")||g.includes("form-ability")||g==="src/index.js"));for(let g of y)h(g)}if(f||o){let g=i.filter(L=>/^src\/form-component\/form-widget\/(edit|ide|read|list|print|search|search-ide)\/.+\.vue$/.test(L)||/^src\/form-component\/form-editor\/.+\.vue$/.test(L)).sort((L,A)=>this._scorePath(A,p,{activeSourceFiles:r,isConfigTask:c,isI18nTask:o,isFormComponentTask:f})-this._scorePath(L,p,{activeSourceFiles:r,isConfigTask:c,isI18nTask:o,isFormComponentTask:f}));for(let L of g)h(L)}}let k=["src/index.js","src/index.ts","src/main.ts","src/App.vue","package.json","pom.xml"];for(let u of k)i.includes(u)&&h(u);let w=[],v=0;for(let u of l.slice(0,Ce)){if(v>_e)break;try{let T=_.Uri.joinPath(e.uri,u),y=await _.workspace.fs.readFile(T),g=Buffer.from(y).toString("utf-8"),A=u.endsWith(".widget.config.js")||u.endsWith(".editor.config.js")||u.endsWith("apaas.json")||u.includes("/form-component-local/")||a&&(u.endsWith("/index.js")||u.endsWith("/index.ts"))?ke:xe;g.length>A&&(g=g.slice(0,A)+`
/* ... truncated ... */`),w.push(`### ${u}
\`\`\`
${g}
\`\`\``),v+=g.length}catch{}}let E=await this._querySymbolIndex(p,e),C=await this._loadSkills(e,n),m=i.slice(0,Te).join(`
`),$=`${p.length?`SEARCH_TERMS:
${p.join(", ")}

`:""}RELEVANT_FILE_CONTENTS:
${w.join(`

`)}${E}

WORKSPACE_FILE_INDEX(${i.length}):
${m}${C}`,M=Math.ceil($.length/Ee);return M>2e4&&console.warn(`[ContextBuilder] Large context: ~${M} tokens (${$.length} chars). Consider reducing file count.`),$}_buildCacheKey(e,t){let n=t.toLowerCase().replace(/\s+/g," ").trim().slice(0,240);return`${e.slice().sort().join(",")}|${n}`}_expandMentionedPathCandidates(e){let t=e.replace(/:\\d+$/g,"").replace(/\\/g,"/"),n=new Set([t]),s=[".umd.min.js",".umd.js",".common.js",".css"];for(let o of s)t.endsWith(o)&&n.add(t.slice(0,-o.length));let i=t.split("/").pop()||t;return n.add(i),[...n].filter(Boolean)}_extractSearchTerms(e,t,n){let s=new Set,i=e||"";for(let c of t)for(let a of this._expandMentionedPathCandidates(c))a.split(/[\\/._-]+/).filter(Boolean).forEach(r=>s.add(r.toLowerCase())),s.add(a.toLowerCase());for(let c of n.slice(0,3))(c.split("/").pop()||c).replace(/\.(vue|js|jsx|ts|tsx|json)$/i,"").split(/[._-]+/).filter(Boolean).forEach(r=>s.add(r.toLowerCase()));let o=i.match(/[A-Za-z][A-Za-z0-9_-]{2,}/g)||[];for(let c of o){let a=c.toLowerCase();Le.has(a)||s.add(a)}return[...s].filter(c=>c.length>=3).sort((c,a)=>a.length-c.length).slice(0,12)}_scorePath(e,t,n){let s=e.toLowerCase(),i=0;n.activeSourceFiles.includes(e)&&(i+=220),n.isConfigTask&&(s.endsWith(".widget.config.js")||s.endsWith(".editor.config.js"))&&(i+=260),n.isConfigTask&&s.includes("/form-component-config/")&&(i+=180),n.isI18nTask&&s.includes("/form-component-local/")&&(i+=220),n.isFormComponentTask&&s.includes("/form-component/")&&(i+=80),n.isFormComponentTask&&s.includes("/form-widget/")&&(i+=90),n.isFormComponentTask&&s.includes("/form-editor/")&&(i+=70);for(let o of t)o&&(s===o?i+=240:s.endsWith(`/${o}`)?i+=180:s.includes(o)&&(i+=o.length>=10?110:55));return i}async _querySymbolIndex(e,t){if(!this.config||!e.length)return"";let n=this.config.get();if(!n.workspaceId||!n.apiBase)return"";let s=e.filter(a=>/^[a-zA-Z]\w{2,}$/.test(a)).slice(0,5);if(!s.length)return"";let i=[],o=0,f=this.config.getHeaders(),c=await Promise.allSettled(s.map(async a=>{let r=this.config.getEndpoint(`/symbols?q=${encodeURIComponent(a)}&limit=5`),p=await fetch(r,{headers:f,signal:AbortSignal.timeout(5e3)});return p.ok?((await p.json())?.symbols||[]).slice(0,3):[]}));for(let a of c){if(o>=se)break;if(!(a.status!=="fulfilled"||!a.value.length))for(let r of a.value){if(o>=se)break;try{let p=_.Uri.joinPath(t.uri,r.file),l=await _.workspace.fs.readFile(p),h=Buffer.from(l).toString("utf-8").split(`
`),x=Math.max(0,r.line-51),S=Math.min(h.length,r.line+50),k=h.slice(x,S).join(`
`);if(k.length>0){let w=`### SYMBOL: ${r.name} @ ${r.file}:${r.line}
\`\`\`
${k.slice(0,2e3)}
\`\`\``;i.push(w),o+=w.length}}catch{}}}return i.length?`

SYMBOL_INDEXED_CONTEXT:
${i.join(`

`)}`:""}async _loadSkills(e,t){try{let n=new _.RelativePattern(e,".claude/skills/*.skill.md"),s=await _.workspace.findFiles(n,void 0,10);if(!s.length)return"";let i=[];for(let o of s.slice(0,2))try{let f=await _.workspace.fs.readFile(o),c=Buffer.from(f).toString("utf-8"),a=_.workspace.asRelativePath(o,!1);i.push(`### SKILL: ${a}
${c.slice(0,4e3)}`)}catch{}return i.length?`

SKILL_GUIDES:
${i.join(`

`)}`:""}catch{return""}}};var I=F(require("vscode")),Ie=[{path:"CLAUDE.md",maxLen:5e3,label:"PROJECT_GUIDE"},{path:"memory.md",maxLen:2e3,label:"MEMORY"},{path:".claude/rules/coding-style.rule.md",maxLen:6e3,label:"RULE"},{path:".claude/rules/mpaas-query-reference.rule.md",maxLen:5e3,label:"RULE"},{path:".claude/rules/dev-workflow.rule.md",maxLen:3e3,label:"RULE"}],je=[".cursor/rules/**/*.mdc",".cursor/rules/**/*.md",".claude/rules/**/*.md",".claude/rules/**/*.rule.md"],re=8,Re=6e3,ae=35e3,U=4e4,Ae=3e5,K=class{cache=null;invalidate(){this.cache=null}async load(){if(this.cache&&Date.now()-this.cache.ts<Ae)return this.cache.text;let e=I.workspace.workspaceFolders;if(!e?.length)return"";let t=e[0],n=[],s=new Set;for(let o of Ie)try{let f=I.Uri.joinPath(t.uri,o.path),c=await I.workspace.fs.readFile(f),a=Buffer.from(c).toString("utf-8");a.trim()&&(n.push(`## ${o.label}: ${o.path}
${a.slice(0,o.maxLen)}`),s.add(o.path))}catch{}for(let o of je)try{let f=await I.workspace.findFiles(new I.RelativePattern(t,o),void 0,re);for(let c of f){let a=I.workspace.asRelativePath(c,!1);if(!s.has(a)){if(n.length>=re)break;try{let r=await I.workspace.fs.readFile(c),p=Buffer.from(r).toString("utf-8"),l=p.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/),h=!1;if(l){let x=l[1];p=l[2],h=/alwaysApply:\s*true/i.test(x)}if(p.trim()){let x=h?ae:Re;n.push(`## RULE: ${a}
${p.slice(0,x)}`),s.add(a)}}catch{}}}}catch{}let i=n.join(`

`);if(i.length>U&&n.length>1){for(;i.length>U&&n.length>1&&n[n.length-1].length<ae/2;){n.pop();i=n.join(`

`)}i.length>U&&(i=i.slice(0,U))}return this.cache={text:i,ts:Date.now()},console.log(`[RuijingAI] guidesLoader: loaded ${n.length} guide/rule files, total ${i.length} chars`),i}};function ce(d,e){let t=Q(d);if(t.edits.length>0)return{type:"edits",edits:t.edits,summary:t.summary};let n=Be(d);if(n.files.length>0)return{type:"plan",plan:n};if(e){let s=Fe(d,e);if(s.length>0)return{type:"edits",edits:s,summary:""}}return{type:"chat"}}function Fe(d,e){let t=/```[\w]*\n([\s\S]*?)```/g,n,s=[];for(;(n=t.exec(d))!==null;){let i=n[1];if(i.split(`
`).length<10)continue;[/^<template>/m,/^<script/m,/^import\s/m,/^export\s+(default|class|function|const)/m,/^package\s+\w/m,/^(public|private)\s+(class|interface)/m,/^#(include|import|pragma)/m,/^(def|class)\s+\w/m].some(c=>c.test(i))&&s.push(i)}return s.length===1?[{path:e,content:s[0],action:"write"}]:[]}function Q(d){let e=[],t="",n=d.match(/^##\s*(?:总结|Summary|概要|Result|Changes|修改总结)[：:]\s*(.+)/m);n&&(t=n[1].trim());let s=/FILE:\s*([^\n]+)\s*\n\s*```[\w]*\n([\s\S]*?)```/g,i;for(;(i=s.exec(d))!==null;){let o=i[1].trim().replace(/^[`'"]+|[`'"]+$/g,"").replace(/^\/+/,""),f=i[2];o&&f&&!o.includes("..")&&e.push({path:o,content:f,action:"write"})}return{edits:e,summary:t}}function Be(d){let e=[],t="",n=d.match(/^##\s*(?:实现方案|计划|Plan|Implementation|Steps|Proposal|Approach|方案)[：:]\s*(.+)/m);n&&(t=n[1].trim());let s=/^\s*\d+\.\s*`([^`]+)`\s*[—\-–]\s*(.+)/gm,i;for(;(i=s.exec(d))!==null;){let o=i[1].trim().replace(/^\/+/,""),f=i[2].trim();o&&f&&e.push({path:o,description:f})}return{summary:t,files:e}}var j=F(require("vscode")),X=class{async apply(e){let t=j.workspace.workspaceFolders;if(!t?.length)return{applied:[],skipped:[{path:"",reason:"No workspace folder"}]};let n=t[0].uri,s=[],i=[];for(let o of e.slice(0,12)){let f=o.path.trim().replace(/\\/g,"/").replace(/^\/+/,"");if(!f||f.includes("..")){i.push({path:f||"(empty)",reason:"Invalid path"});continue}if(o.action==="delete"){try{let c=j.Uri.joinPath(n,f);await j.workspace.fs.delete(c,{recursive:!0}),s.push({path:f,action:"delete"})}catch(c){i.push({path:f,reason:c.message||"Delete failed"})}continue}if(!o.content){i.push({path:f,reason:"Missing content"});continue}try{let c=j.Uri.joinPath(n,f),a=new j.WorkspaceEdit,r=Buffer.from(o.content,"utf-8");a.createFile(c,{overwrite:!0,ignoreIfExists:!1,contents:r}),await j.workspace.applyEdit(a)?s.push({path:f,action:o.action}):i.push({path:f,reason:"applyEdit returned false"})}catch(c){i.push({path:f,reason:c.message||"Write failed"})}}return{applied:s,skipped:i}}};var q=class{constructor(e,t,n,s){this.llmClient=e;this.fileWriter=t;this.contextBuilder=n;this.guidesLoader=s}pendingPlan=null;hasPending(){return this.pendingPlan!==null}store(e){this.pendingPlan=e}clear(){this.pendingPlan=null}getPending(){return this.pendingPlan}async execute(e,t,n,s){this.pendingPlan=null;let i=[],o=[],f=[],c=await this.contextBuilder.build(e.userMsg||""),a=await this.guidesLoader.load();for(let l=0;l<e.files.length&&!s.isCancellationRequested;l++){let h=e.files[l];n.progress(`\u751F\u6210\u4E2D (${l+1}/${e.files.length}) ${h.path}`),n.markdown(`
\u23F3 **\u751F\u6210\u4E2D (${l+1}/${e.files.length})** \`${h.path}\`...
`);let x=e.files.filter((m,P)=>P!==l).map(m=>`- \`${m.path}\` \u2014 ${m.description}`).join(`
`),S=f.map(m=>`### ${m.path}
\`\`\`
${m.excerpt}
\`\`\``).join(`
`),k=this._getFileRoleHint(h.path),v=[{role:"system",content:["\u4F60\u662F IDE \u4EE3\u7801\u4FEE\u6539\u4EE3\u7406\u3002\u73B0\u5728\u6309\u7167\u5DF2\u786E\u8BA4\u7684\u8BA1\u5212\u9010\u6587\u4EF6\u751F\u6210\u4EE3\u7801\u3002",`\u5F53\u524D\u4EFB\u52A1\uFF1A\u751F\u6210 FILE: ${h.path}`,`\u6587\u4EF6\u63CF\u8FF0\uFF1A${h.description}`,k?`\u6587\u4EF6\u89D2\u8272\u63D0\u793A\uFF1A${k}`:"",`
\u6574\u4F53\u8BA1\u5212\uFF1A${e.summary}`,`\u5176\u4ED6\u6587\u4EF6\uFF1A
${x}`,S?`
\u5DF2\u751F\u6210\u7684\u6587\u4EF6\uFF08\u4F9B\u53C2\u8003\u63A5\u53E3/\u7C7B\u540D\uFF09\uFF1A
${S}`:"",`
\u8F93\u51FA\u683C\u5F0F\uFF1A\u53EA\u8F93\u51FA\u8FD9\u4E00\u4E2A\u6587\u4EF6\u3002\u5148\u5199 FILE: \u8DEF\u5F84\uFF0C\u7136\u540E\u7D27\u8DDF\u5B8C\u6574\u4EE3\u7801\u5757\u3002\u4EE3\u7801\u5FC5\u987B\u5B8C\u6574\uFF0C\u4E0D\u8981\u7701\u7565\u4EFB\u4F55\u90E8\u5206\u3002`,a?`
PROJECT_RULES:
${a}`:""].filter(Boolean).join(`
`)}];c?v.push({role:"user",content:`\u5F53\u524D\u5DE5\u4F5C\u533A\u4EE3\u7801\uFF1A
${c.slice(0,5e3)}

---
\u8BF7\u751F\u6210 ${h.path}`}):v.push({role:"user",content:`\u8BF7\u751F\u6210 ${h.path}\uFF1A${h.description}

\u539F\u59CB\u9700\u6C42\uFF1A${e.userMsg||""}`});let E="";try{for await(let m of this.llmClient.stream({model:t,messages:v,maxTokens:8192,token:s}))E+=m,n.markdown(m)}catch(m){o.push({path:h.path,reason:m.message||"LLM error"}),n.markdown(`
\u26A0\uFE0F \`${h.path}\` \u751F\u6210\u5931\u8D25: ${m.message}
`);continue}let C=Q(E);if(C.edits.length>0){let m=await this.fileWriter.apply(C.edits);i.push(...m.applied.map(P=>P.path)),o.push(...m.skipped);for(let P of C.edits){let $=P.content.split(`
`);f.push({path:P.path,excerpt:$.slice(0,50).join(`
`)})}n.markdown(`
\u2705 \`${h.path}\` \u5DF2\u5199\u5165
`),this.contextBuilder.markDirty()}else o.push({path:h.path,reason:"\u672A\u89E3\u6790\u5230\u6587\u4EF6\u5185\u5BB9"}),n.markdown(`
\u26A0\uFE0F \`${h.path}\` \u89E3\u6790\u5931\u8D25\uFF0C\u8DF3\u8FC7
`)}let r=i.map(l=>`- \u2705 ${l}`).join(`
`),p=o.map(l=>`- \u274C ${l.path}: ${l.reason}`).join(`
`);n.markdown(`
---
**\u5168\u90E8\u5B8C\u6210 (${i.length}/${e.files.length})**`+(r?`

\u5DF2\u5199\u5165\uFF1A
${r}`:"")+(p?`

\u672A\u6210\u529F\uFF1A
${p}`:"")+`
`)}_getFileRoleHint(e){if(e.endsWith(".widget.config.js"))return"\u8FD9\u662F\u7EC4\u4EF6\u914D\u7F6E\u6587\u4EF6\u3002\u4E25\u683C\u9075\u5FAA PROJECT_RULES \u4E2D\u7684 widget config \u7ED3\u6784\uFF1Aversion, code, desc, instance, component(\u6240\u6709\u6E32\u67D3\u6A21\u5F0F), widget(display/allow/default/validator/special/editor), componentModelField, client.mobile\u3002";let t=e.match(/form-widget\/(ide|edit|read|list|print|search|search-ide)\//);if(t){let n=t[1];return`\u8FD9\u662F ${n} \u6E32\u67D3\u6A21\u5F0F\u7EC4\u4EF6\u3002\u4F7F\u7528: ${{ide:"FormWidgetMixin (@/mixin/form-widget.mixin)",edit:"FormWidgetMixin (@/mixin/form-widget.mixin)",read:"FormWidgetMixin (@/mixin/form-widget.mixin)",list:"\u65E0mixin\uFF0C\u4F7F\u7528 inject:['listEngine'] + props:['componentConfig','formValue','propKey']",print:"PrintWidgetMixin (@/mixin/print-widget.mixin)",search:"SearchWidgetMixin (@/mixin/search-widget.mixin)","search-ide":"SearchIdeWidgetMixin (@/mixin/search-ide-widget.mixin)"}[n]||"\u53C2\u8003 PROJECT_RULES"}\u3002\u53C2\u8003 PROJECT_RULES \u4E2D\u7684\u540C\u6A21\u5F0F\u7EC4\u4EF6\u793A\u4F8B\u3002`}return e.endsWith(".editor.config.js")?"\u8FD9\u662F\u7F16\u8F91\u5668\u914D\u7F6E\u6587\u4EF6\u3002\u5FC5\u987B\u5305\u542B code, editorConfigType, componentName, configProperty \u56DB\u4E2A\u5B57\u6BB5\u3002":/form-editor\/.*\.vue$/.test(e)?"\u8FD9\u662F\u8868\u5355\u8BBE\u8BA1\u5668\u53F3\u4FA7\u5C5E\u6027\u9762\u677F\u7EC4\u4EF6\u3002\u4F7F\u7528 EditorFormConfigMixin (@/mixin/form-config.mixin)\u3002":e==="src/apaas.json"?"\u5E73\u53F0\u5143\u6570\u636E\u6587\u4EF6\u3002\u4FDD\u7559\u5DF2\u6709\u5185\u5BB9\uFF0C\u53EA\u6DFB\u52A0/\u4FEE\u6539\u5F53\u524D\u7EC4\u4EF6\u7684\u6761\u76EE\u3002\u6CE8\u610F type \u5B57\u6BB5\u8981\u4E0E widget config \u7684 code \u4E00\u81F4\u3002":/\/index\.js$/.test(e)?"\u805A\u5408\u5BFC\u51FA\u6587\u4EF6\u3002\u5BFC\u5165\u5E76\u5BFC\u51FA\u65B0\u7EC4\u4EF6\uFF0C\u4FDD\u7559\u5DF2\u6709\u7684\u5BFC\u5165\u4E0D\u8981\u5220\u9664\u3002":""}};var le=`\u4F60\u662F\u96C6\u6210\u5728 VS Code \u98CE\u683C IDE \u91CC\u7684\u4E2D\u6587\u7F16\u7A0B\u52A9\u624B\u3002\u4F60\u53EF\u4EE5\u56DE\u7B54\u95EE\u9898\uFF0C\u4E5F\u53EF\u4EE5\u76F4\u63A5\u4FEE\u6539\u4EE3\u7801\u6587\u4EF6\u3002

## \u4F60\u7684\u80FD\u529B
\u4F60\u80FD\u81EA\u4E3B\u5224\u65AD\u7528\u6237\u7684\u610F\u56FE\u5E76\u9009\u62E9\u5408\u9002\u7684\u54CD\u5E94\u65B9\u5F0F\uFF1A

### \u6A21\u5F0F A\uFF1A\u5BF9\u8BDD\uFF08\u7528\u6237\u5728\u63D0\u95EE/\u8BA8\u8BBA/\u770B\u4EE3\u7801/\u770B\u62A5\u9519\uFF09
\u76F4\u63A5\u7528 markdown \u56DE\u7B54\u3002\u4E0D\u8981\u8F93\u51FA FILE \u5757\u3002

### \u6A21\u5F0F B\uFF1A\u4EE3\u7801\u751F\u6210\uFF08\u7528\u6237\u786E\u8BA4\u4E86\u65B9\u6848\uFF0C\u6216\u660E\u786E\u8981\u6C42\u6539\u4EE3\u7801/\u5199\u4EE3\u7801/\u4FEEbug\uFF09
\u6309\u4EE5\u4E0B\u683C\u5F0F\u8F93\u51FA\u6587\u4EF6\uFF1A
## \u603B\u7ED3\uFF1A\u7B80\u77ED\u63CF\u8FF0
FILE: src/\u76F8\u5BF9\u8DEF\u5F84/Xxx.java
\`\`\`java
// \u6587\u4EF6\u5B8C\u6574\u5185\u5BB9
\`\`\`
\u4EE3\u7801\u5757\u5FC5\u987B\u5305\u542B\u6587\u4EF6\u5B8C\u6574\u5185\u5BB9\uFF0C\u4E0D\u8981\u7701\u7565\u3001\u4E0D\u8981\u7528 // ... \u4EE3\u66FF\u3002\u4E0D\u9700\u8981\u6539\u7684\u6587\u4EF6\u4E0D\u8981\u8F93\u51FA\u3002

### \u6A21\u5F0F C\uFF1A\u65B9\u6848\u89C4\u5212\uFF08\u7528\u6237\u63CF\u8FF0\u4E86\u4E00\u4E2A\u65B0\u9700\u6C42\uFF0C\u9700\u8981\u521B\u5EFA\u591A\u4E2A\u6587\u4EF6\uFF09
\u5148\u8F93\u51FA\u5B9E\u73B0\u65B9\u6848\uFF08\u4E0D\u5199\u4EE3\u7801\uFF09\uFF0C\u8BA9\u7528\u6237\u786E\u8BA4\u540E\u518D\u751F\u6210\uFF1A
## \u5B9E\u73B0\u65B9\u6848\uFF1A\u7B80\u77ED\u63CF\u8FF0
1. \`\u6587\u4EF6\u8DEF\u5F84\` \u2014 \u6587\u4EF6\u804C\u8D23\u8BF4\u660E
2. \`\u6587\u4EF6\u8DEF\u5F84\` \u2014 \u6587\u4EF6\u804C\u8D23\u8BF4\u660E
\u8BF7\u7528\u6237\u786E\u8BA4\u540E\u5F00\u59CB\u751F\u6210\u3002

## \u91CD\u8981\u89C4\u5219
- \u53EA\u8981\u7528\u6237\u8981\u6C42\u5BF9\u4EE3\u7801\u505A\u4EFB\u4F55\u4FEE\u6539\uFF08\u5305\u62EC\u52A0\u6CE8\u91CA\u3001\u91CD\u6784\u3001\u683C\u5F0F\u5316\u3001\u4FEEbug\u3001\u52A0\u529F\u80FD\uFF09\uFF0C\u90FD\u5FC5\u987B\u7528\u6A21\u5F0F B \u8F93\u51FA\u5B8C\u6574 FILE \u5757
- \u5982\u679C\u4E0A\u4E00\u8F6E\u4F60\u5DF2\u7ECF\u8F93\u51FA\u4E86\u65B9\u6848\uFF0C\u7528\u6237\u8BF4\u300C\u786E\u8BA4/\u5F00\u59CB/\u597D\u7684/ok\u300D\uFF0C\u76F4\u63A5\u8FDB\u5165\u6A21\u5F0F B \u751F\u6210\u4EE3\u7801
- \u5982\u679C\u7528\u6237\u8BF4\u300C\u6539\u4E00\u4E0B/\u4FEE\u590D/\u76F4\u63A5\u6539/\u52A0\u6CE8\u91CA/\u4F18\u5316\u300D\u7B49\uFF0C\u76F4\u63A5\u8FDB\u5165\u6A21\u5F0F B
- \u53EA\u6709\u7528\u6237\u7EAF\u7CB9\u5728\u95EE\u95EE\u9898\u3001\u770B\u4EE3\u7801\u3001\u770B\u62A5\u9519\u65F6\u624D\u7528\u6A21\u5F0F A
- \u6C38\u8FDC\u4E0D\u8981\u5728\u6A21\u5F0F A \u4E2D\u8F93\u51FA\u4EE3\u7801\u5757\u6765\u5C55\u793A\u4FEE\u6539\u540E\u7684\u4EE3\u7801\u2014\u2014\u5982\u679C\u8981\u5C55\u793A\u4FEE\u6539\uFF0C\u5C31\u7528\u6A21\u5F0F B \u7684 FILE \u683C\u5F0F

## \u5176\u4ED6
- \u9ED8\u8BA4\u4E2D\u6587\u56DE\u7B54
- \u4E0D\u8981\u8F93\u51FA <think>\u3001TOOL_CALL \u7B49\u6807\u8BB0
- \u4E0D\u8981\u8BF4\u65E0\u6CD5\u8BBF\u95EE\u6587\u4EF6\uFF0C\u57FA\u4E8E\u5DF2\u63D0\u4F9B\u7684\u4EE3\u7801\u4E0A\u4E0B\u6587\u56DE\u7B54
- \u5982\u679C\u7528\u6237\u6CA1\u6709\u663E\u5F0F\u7ED9\u6587\u4EF6\u8DEF\u5F84\uFF0C\u5148\u7ED3\u5408 WORKSPACE_CONTEXT \u91CC\u5DF2\u6709\u7684\u6587\u4EF6\u5217\u8868\u3001\u5F53\u524D\u6253\u5F00\u7684\u6E90\u7801\u6587\u4EF6\u548C\u9879\u76EE\u89C4\u5219\uFF0C\u81EA\u4E3B\u5B9A\u4F4D\u6700\u76F8\u5173\u7684\u6E90\u7801\u6587\u4EF6
- \u5982\u679C WORKSPACE_CONTEXT \u91CC\u7684 RELEVANT_FILE_CONTENTS \u5DF2\u7ECF\u5305\u542B\u5019\u9009\u6E90\u7801\u3001\u914D\u7F6E\u6587\u4EF6\u6216\u8BED\u8A00\u5305\uFF0C\u5C31\u89C6\u4E3A\u4F60\u5DF2\u7ECF\u62FF\u5230\u4E86\u6587\u4EF6\u5185\u5BB9\uFF0C\u4E0D\u8981\u518D\u6B21\u8981\u6C42\u7528\u6237\u624B\u52A8\u7C98\u8D34\u540C\u4E00\u4E2A\u6587\u4EF6
- \u4E0D\u8981\u8F7B\u6613\u8981\u6C42\u7528\u6237\u624B\u52A8\u7C98\u8D34\u6587\u4EF6\u5185\u5BB9\uFF1B\u53EA\u6709\u5F53\u5DE5\u4F5C\u533A\u4E0A\u4E0B\u6587\u91CC\u786E\u5B9E\u6CA1\u6709\u76F8\u5173\u6587\u4EF6\uFF0C\u6216\u8005\u6587\u4EF6\u660E\u786E\u7F3A\u5931\u65F6\uFF0C\u624D\u8BF4\u660E\u7F3A\u5C11\u4EC0\u4E48
- \u5982\u679C\u5F53\u524D\u770B\u5230\u7684\u662F \`.umd.js\`\u3001\`.common.js\`\u3001\`.min.js\`\u3001\`dist/\`\u3001\`build/\` \u4E4B\u7C7B\u6784\u5EFA\u4EA7\u7269\uFF0C\u8BF7\u4F18\u5148\u56DE\u6EAF \`src/\` \u4E0B\u6E90\u7801\u548C\u914D\u7F6E\u6587\u4EF6\uFF0C\u4E0D\u8981\u628A\u6784\u5EFA\u4EA7\u7269\u5F53\u6210\u552F\u4E00\u7F16\u8F91\u76EE\u6807`,G=class{constructor(e,t){this.config=e;this.modelSelector=t;this.llmClient=new B(e),this.contextBuilder=new H,this.guidesLoader=new K,this.fileWriter=new X,this.planMode=new q(this.llmClient,this.fileWriter,this.contextBuilder,this.guidesLoader)}llmClient;contextBuilder;guidesLoader;fileWriter;planMode;modelsLoaded=!1;externalHistoryNoticeShown=new Set;async handle(e,t,n,s){this.modelsLoaded||(this.modelsLoaded=!0,this.modelSelector.loadModels(this.llmClient).catch(()=>{}));let i=e.prompt.trim();if(!i)return n.markdown("\u8BF7\u8F93\u5165\u60A8\u7684\u95EE\u9898\u6216\u9700\u6C42\u3002"),{};if(this._canUseCodingPipeline()){this.planMode.hasPending()&&this.planMode.clear();try{return this._announceExternalHistoryContext(t,n),await this._handleViaCodingPipeline(i,n,s),{}}catch(o){console.warn("[RuijingAI] coding pipeline fallback to legacy mode",o),n.markdown(`

\u26A0\uFE0F \u7EDF\u4E00 Coding Runtime \u6682\u65F6\u4E0D\u53EF\u7528\uFF0C\u5DF2\u56DE\u9000\u5230\u672C\u5730\u517C\u5BB9\u6A21\u5F0F\u3002
`)}}try{if(this.planMode.hasPending()){if(ne(i)){let v=this.planMode.getPending(),E=this.modelSelector.resolve(!0);return n.markdown(`\u{1F4CB} \u8BA1\u5212\u5DF2\u786E\u8BA4\uFF0C\u5F00\u59CB\u9010\u6587\u4EF6\u751F\u6210...
`),await this.planMode.execute(v,E,n,s),{}}if(ie(i))return this.planMode.clear(),n.markdown("\u5DF2\u53D6\u6D88\u8BA1\u5212\uFF0C\u6587\u4EF6\u672A\u53D8\u52A8\u3002"),{};this.planMode.clear()}let[o,f]=await Promise.all([this.contextBuilder.build(i),this.guidesLoader.load()]),c=Z(i),a=this.modelSelector.resolve(c),r=i,p=b.window.activeTextEditor,l=p?b.workspace.asRelativePath(p.document.uri,!1):void 0,h=l?this._isGeneratedArtifact(l):!1;if(c&&l&&!this._mentionsSpecificFile(i)&&this._shouldScopeToActiveFile(l)){let v="";p&&(v=p.document.getText(),v.length>8e3&&(v=v.slice(0,8e3)+`
/* ... truncated ... */`)),r=`${i}

\u8BF7\u53EA\u9488\u5BF9\u5F53\u524D\u6253\u5F00\u7684\u6587\u4EF6\u64CD\u4F5C: ${l}

\u5F53\u524D\u6587\u4EF6\u5B8C\u6574\u5185\u5BB9:
\`\`\`
${v}
\`\`\``}else c&&!this._mentionsSpecificFile(i)&&(r=`${i}

\u8BF7\u5148\u6839\u636E\u5F53\u524D\u5DE5\u4F5C\u533A\u5DF2\u6709\u6E90\u7801\u548C\u89C4\u5219\u6587\u4EF6\uFF0C\u81EA\u4E3B\u5B9A\u4F4D\u6700\u76F8\u5173\u7684\u5B9E\u73B0\u6587\u4EF6\u4E0E\u56FD\u9645\u5316\u6587\u4EF6\uFF1B\u9664\u975E\u5DE5\u4F5C\u533A\u4E2D\u786E\u5B9E\u4E0D\u5B58\u5728\uFF0C\u5426\u5219\u4E0D\u8981\u8981\u6C42\u7528\u6237\u624B\u52A8\u63D0\u4F9B\u6587\u4EF6\u5185\u5BB9\u3002${h?`

\u6CE8\u610F\uFF1A\u5F53\u524D\u6FC0\u6D3B\u6587\u4EF6\u770B\u8D77\u6765\u662F\u6784\u5EFA\u4EA7\u7269\u6216\u6253\u5305\u8F93\u51FA\uFF0C\u8BF7\u4E0D\u8981\u56F4\u7ED5\u5B83\u5B9A\u4F4D\uFF0C\u4F18\u5148\u5BFB\u627E src/ \u4E0B\u7684\u6E90\u7801\u3001\u914D\u7F6E\u6587\u4EF6\u548C\u8BED\u8A00\u5305\u3002`:""}`);let x=this._buildMessages(r,o,f,t),S=f.length>1e4?8192:4096,k="";for await(let v of this.llmClient.stream({model:a,messages:x,maxTokens:S,token:s}))k+=v,n.markdown(v);if(!k)return n.markdown("\u6A21\u578B\u672A\u8FD4\u56DE\u5185\u5BB9\uFF0C\u8BF7\u91CD\u8BD5\u3002"),{};let w=ce(k,l);if(w.type==="edits"){let v=await this.fileWriter.apply(w.edits);this.contextBuilder.markDirty();let E=v.applied.map(m=>`- \u2705 ${m.path}`).join(`
`),C=v.skipped.map(m=>`- \u274C ${m.path}: ${m.reason}`).join(`
`);(E||C)&&n.markdown(`

---
**\u6587\u4EF6\u64CD\u4F5C\u7ED3\u679C\uFF1A**`+(E?`
${E}`:"")+(C?`
${C}`:"")+`
`)}else w.type==="plan"&&(w.plan.userMsg=i,this.planMode.store(w.plan),n.markdown(`

---
\u8F93\u5165 **\u786E\u8BA4** \u5F00\u59CB\u9010\u6587\u4EF6\u751F\u6210\u4EE3\u7801\uFF0C\u6216 **\u53D6\u6D88** \u653E\u5F03\u3002\u4E5F\u53EF\u4EE5\u56DE\u590D\u8C03\u6574\u8981\u6C42\u3002
`));return{}}catch(o){return console.error("[RuijingAI] handler error",o),n.markdown(`

\u274C \u9519\u8BEF: ${o.message||"\u672A\u77E5\u9519\u8BEF"}`),{}}}getFollowupProvider(){return{provideFollowups:(e,t,n)=>this.planMode.hasPending()?[{prompt:"\u786E\u8BA4",label:"\u2705 \u786E\u8BA4\u5F00\u59CB\u751F\u6210"},{prompt:"\u53D6\u6D88",label:"\u274C \u53D6\u6D88\u8BA1\u5212"}]:[]}}_canUseCodingPipeline(){let e=this.config.get();return!!(e.workspaceId&&e.ideToken&&(e.harnessApiBase||e.apiBase))}_buildPipelineMessage(e){let t=b.window.activeTextEditor,n=t?b.workspace.asRelativePath(t.document.uri,!1):"";return n?this._isGeneratedArtifact(n)?`${e}

\u8865\u5145\u4E0A\u4E0B\u6587\uFF1A\u5F53\u524D\u6FC0\u6D3B\u6587\u4EF6\u662F\u6784\u5EFA\u4EA7\u7269 ${n}\uFF0C\u8BF7\u4F18\u5148\u68C0\u67E5 src/ \u4E0B\u6E90\u7801\u3001\u914D\u7F6E\u6587\u4EF6\u548C\u5165\u53E3\u6587\u4EF6\uFF0C\u4E0D\u8981\u56F4\u7ED5\u6784\u5EFA\u4EA7\u7269\u4FEE\u6539\u3002`:`${e}

\u8865\u5145\u4E0A\u4E0B\u6587\uFF1A\u5F53\u524D\u6253\u5F00\u6587\u4EF6\u4E3A ${n}\u3002\u5982\u679C\u672C\u6B21\u9700\u6C42\u4E0E\u5B83\u76F8\u5173\uFF0C\u8BF7\u4F18\u5148\u68C0\u67E5\u5B83\u4EE5\u53CA\u76F8\u90BB\u7684\u6E90\u7801\u3001\u914D\u7F6E\u548C\u5165\u53E3\u6587\u4EF6\u3002`:e}async _handleViaCodingPipeline(e,t,n){let s=Z(e),i=this.modelSelector.resolve(s),o=this._buildPipelineMessage(e),f=!1,c=!1,a=!1;for await(let r of this.llmClient.streamCodingPipeline({message:o,selectedModel:i,conversationId:this.config.get().conversationId,token:n})){let p=r?.type||"";if(p==="step"){let l=r.step||"",h=r.status||"",x=this._formatPipelineStep(l,h,r.data||{});x&&(c=!0,t.markdown(x));continue}if(p==="content"){let l=O(String(r.content||""));l.trim()&&(c=!0,a=!0,t.markdown(l));continue}if(p==="agent_thinking_delta"){let l=O(String(r.content||""));l&&(f=!0,c=!0,a=!0,t.markdown(l));continue}if(p==="agent_thinking"){if(f)continue;let l=O(String(r.content||""));l.trim()&&(c=!0,a=!0,t.markdown(l));continue}if(p==="agent_tool"){let l=r.tool_display||r.tool||"\u5DE5\u5177",h=String(r.input_preview||"").trim();c=!0,t.markdown(h?`

\u{1F527} **${l}** \`${h}\`
`:`

\u{1F527} **${l}**
`);continue}if(p==="agent_result"){let l=String(r.output_preview||"").trim();l&&(c=!0,t.markdown(r.is_error?`
> \u274C ${l}

`:`
> \u2705 ${l}

`));continue}if(p==="agent_done"){let l=O(String(r.result||""));l.trim()&&l.trim().toLowerCase()!=="completed"&&!a&&(c=!0,a=!0,t.markdown(`

${l}
`));continue}if(p==="agent_error"||p==="error")throw new Error(r.message||"Coding pipeline failed");if(p==="scene_detected"||p==="done"){r.conversation_id&&await this.config.updateWorkspaceConfig({conversationId:Number(r.conversation_id)});continue}}c||t.markdown("\u5DF2\u5904\u7406\u5B8C\u6210\u3002")}_formatPipelineStep(e,t,n){return e==="detect_scene"&&t==="running"?`

\u{1F50D} \u6B63\u5728\u8BC6\u522B\u5F00\u53D1\u573A\u666F...
`:e==="detect_scene"&&t==="done"?`

\u2705 \u5DF2\u8BC6\u522B\u573A\u666F\uFF1A${n.scene_type||"coding"}
`:e==="create_workspace"&&t==="running"?`

\u{1F4C1} \u6B63\u5728\u521B\u5EFA\u5DE5\u4F5C\u533A\u4E0E\u521D\u59CB\u5316\u811A\u624B\u67B6...
`:e==="create_workspace"&&t==="done"?`

\u2705 \u5DE5\u4F5C\u533A\u5DF2\u5C31\u7EEA\uFF1A**${n.display_name||n.project_name||n.workspace_id||"\u5DE5\u4F5C\u533A"}**
`:e==="generate"&&t==="running"?`

\u{1F916} \u6B63\u5728\u5206\u6790\u4EE3\u7801\u5E76\u6267\u884C\u4FEE\u6539...
`:e==="generate"&&t==="done"?`

\u2705 \u672C\u8F6E\u7F16\u7801\u5DF2\u5B8C\u6210
`:e==="build"&&t==="running"?`

\u{1F3D7}\uFE0F \u6B63\u5728\u6784\u5EFA\u6253\u5305...
`:e==="build"&&t==="done"?`

\u2705 \u6784\u5EFA\u5B8C\u6210
`:e==="debug"&&t==="running"?`

\u{1F9EA} \u6B63\u5728\u542F\u52A8\u8C03\u8BD5\u73AF\u5883...
`:e==="debug"&&t==="done"?`

\u2705 \u8C03\u8BD5\u73AF\u5883\u5DF2\u542F\u52A8
`:""}_buildMessages(e,t,n,s){let o=[{role:"system",content:[le,t?`
WORKSPACE_CONTEXT:
${t.slice(0,18e3)}`:"",n?`
PROJECT_RULES:
${n}`:""].filter(Boolean).join(`
`)}];if(s.history.length>0){for(let a of s.history.slice(-6))if(a instanceof b.ChatRequestTurn)o.push({role:"user",content:a.prompt.slice(0,1500)});else if(a instanceof b.ChatResponseTurn){let r="";for(let p of a.response)p instanceof b.ChatResponseMarkdownPart&&(r+=p.value.value);r&&o.push({role:"assistant",content:r.slice(0,2e3)})}}else{let a=this._loadExternalChatHistoryPayload();if(a.messages.length>0){o.push({role:"system",content:"\u4EE5\u4E0B\u662F\u7528\u6237\u5728 AI Coding \u5BF9\u8BDD\u4E2D\u7684\u5386\u53F2\u8BB0\u5F55\uFF08\u6765\u81EA Web \u7AEF\uFF09\uFF0C\u8BF7\u7ED3\u5408\u8FD9\u4E9B\u4E0A\u4E0B\u6587\u56DE\u7B54\uFF1A"});for(let r of a.messages.slice(-8))o.push({role:r.role,content:r.content.slice(0,2e3)})}}o.push({role:"user",content:e});let c=o.reduce((a,r)=>a+r.content.length,0);if(c>8e4){let a=c-8e4,r=Math.max(4e3,18e3-a);o[0]={role:"system",content:[le,t?`
WORKSPACE_CONTEXT (trimmed):
${t.slice(0,r)}`:"",n?`
PROJECT_RULES:
${n}`:""].filter(Boolean).join(`
`)}}return o}_announceExternalHistoryContext(e,t){if(e.history.length>0)return;let n=this._loadExternalChatHistoryPayload();if(!n.messages.length)return;let s=this._getExternalHistoryNoticeKey();this.externalHistoryNoticeShown.has(s)||(this.externalHistoryNoticeShown.add(s),t.markdown(`

\u2139\uFE0F \u5DF2\u52A0\u8F7D\u5F53\u524D\u5DE5\u4F5C\u533A\u6700\u8FD1 ${n.messages.length} \u6761 AI Coding \u5386\u53F2\u4F5C\u4E3A\u4E0A\u4E0B\u6587\u3002\u53D7 IDE \u539F\u751F\u804A\u5929\u9762\u677F\u9650\u5236\uFF0C\u65E7\u6D88\u606F\u4E0D\u4F1A\u81EA\u52A8\u56DE\u653E\u663E\u793A\u5728\u8FD9\u91CC\u3002

`))}_getExternalHistoryNoticeKey(){let e=this.config.get();return e.workspaceId?e.workspaceId:b.workspace.workspaceFolders?.[0]?.uri.fsPath||"default"}_loadExternalChatHistoryPayload(){try{let e=b.workspace.workspaceFolders;if(!e?.length)return{conversationId:null,messages:[]};let t=require("path"),n=require("fs"),s=t.join(e[0].uri.fsPath,".vscode","chat-history.json");if(!n.existsSync(s))return{conversationId:null,messages:[]};let i=JSON.parse(n.readFileSync(s,"utf-8"));if(Array.isArray(i?.messages))return{conversationId:Number.isFinite(Number(i.conversation_id))?Number(i.conversation_id):null,messages:i.messages.filter(o=>o.role&&o.content)}}catch{}return{conversationId:null,messages:[]}}_mentionsSpecificFile(e){return/[A-Za-z0-9_\-]+\.\w{1,6}/.test(e)||/\bsrc\//.test(e)}_shouldScopeToActiveFile(e){let t=e.replace(/\\/g,"/");return/^\.cursor\/rules\//.test(t)||/^\.claude\/rules\//.test(t)||this._isGeneratedArtifact(t)||/\.(md|mdc|txt)$/i.test(t)?!1:/\.(vue|js|jsx|ts|tsx|json|java|xml|yml|yaml|properties|scss|css|less|html)$/i.test(t)}_isGeneratedArtifact(e){let t=e.replace(/\\/g,"/").toLowerCase();return/(^|\/)(dist|build|coverage|out|target|tmp|temp)\//.test(t)||/(^|\/)public\//.test(t)&&!t.startsWith("src/")?!0:/\.(umd(\.min)?|common|min|bundle)\.js$/i.test(t)}};var R=F(require("vscode")),z=class d{constructor(e){this.config=e;this.statusBarItem=R.window.createStatusBarItem(R.StatusBarAlignment.Right,100),this.statusBarItem.command="ruijing-ai.selectModel",this.statusBarItem.tooltip="\u777F\u9CB8AI: \u9009\u62E9\u6A21\u578B",this.updateLabel(),this.statusBarItem.show();let t=R.commands.registerCommand("ruijing-ai.selectModel",()=>this.showPicker());this.disposables.push(t,this.statusBarItem)}statusBarItem;models=[];selectedModel=null;autoMode=!0;disposables=[];static EDIT_MODELS=["claude-sonnet-4-6","claude-sonnet-4","gpt-5.4","gpt-4o"];static CHAT_MODELS=["qwen3-coder-next","qwen-plus","gpt-5.4","MiniMax-M2.7"];resolve(e){let t=this.config.get();if(!this.autoMode&&this.selectedModel)return this.selectedModel;let n=e?d.EDIT_MODELS:d.CHAT_MODELS;for(let i of n){let o=this.findModelByNeedle(i);if(o)return o.id}let s=this.findModelByNeedle(t.model);return s?s.id:t.model||"MiniMax-M2.7"}async loadModels(e){this.models=await e.fetchModels(),this.autoMode=this.config.get().autoMode,this.updateLabel()}updateLabel(){if(this.autoMode)this.statusBarItem.text="$(sparkle) Auto";else{let t=(this.findModelByNeedle(this.selectedModel||this.config.get().model)?.name||this.selectedModel||this.config.get().model).replace(/^claude-/,"").replace(/^gpt-/,"GPT-").slice(0,15);this.statusBarItem.text=`$(sparkle) ${t}`}}findModelByNeedle(e){let t=(e||"").trim().toLowerCase();if(t)return this.models.find(n=>{let s=(n.id||"").toLowerCase(),i=(n.name||"").toLowerCase();return s===t||i===t||s.includes(t)||i.includes(t)})}async showPicker(){let e=[{label:"$(sparkle) Auto\uFF08\u63A8\u8350\uFF09",description:"Edit \u7528 Claude Sonnet\uFF0CChat \u7528 Qwen",picked:this.autoMode},{label:"",kind:R.QuickPickItemKind.Separator}];for(let n of this.models)e.push({label:n.name||n.id,description:n.provider||"",picked:!this.autoMode&&this.selectedModel===n.id});this.models.length===0&&e.push({label:this.config.get().model,description:"\u9ED8\u8BA4\u6A21\u578B"});let t=await R.window.showQuickPick(e,{title:"\u777F\u9CB8AI: \u9009\u62E9\u6A21\u578B",placeHolder:"\u9009\u62E9 AI \u6A21\u578B"});if(t){if(t.label.includes("Auto"))this.autoMode=!0,this.selectedModel=null;else{this.autoMode=!1;let n=this.models.find(s=>(s.name||s.id)===t.label);this.selectedModel=n?.id||t.label}this.updateLabel()}}dispose(){for(let e of this.disposables)e.dispose()}};var J=F(require("vscode")),N=F(require("path")),V=class{constructor(e){this.context=e}_cached=null;_cachedAt=0;get(){return this._cached&&Date.now()-this._cachedAt<3e4?this._cached:(this._cached=this._load(),this._cachedAt=Date.now(),this._cached)}invalidate(){this._cached=null}_load(){let e=J.workspace.getConfiguration("ruijing-ai"),t={},n=J.workspace.workspaceFolders;if(n?.length)try{let s=N.join(n[0].uri.fsPath,".vscode","ruijing-ai.json"),i=require("fs");i.existsSync(s)&&(t=JSON.parse(i.readFileSync(s,"utf-8")))}catch{}return{workspaceId:t.workspaceId||"",ideToken:t.ideToken||"",apiBase:t.apiBase||e.get("apiBase")||"",harnessApiBase:t.harnessApiBase||this._deriveHarnessApiBase(t.apiBase||e.get("apiBase")||""),apiKey:t.apiKey||e.get("apiKey")||"",model:t.model||e.get("model")||"MiniMax-M2.7",conversationId:this._parseConversationId(t.conversationId),autoMode:e.get("autoMode")??!0}}async updateWorkspaceConfig(e){let t=J.workspace.workspaceFolders;if(!t?.length)return;let n=require("fs"),s=N.join(t[0].uri.fsPath,".vscode","ruijing-ai.json"),i={};try{n.existsSync(s)&&(i=JSON.parse(n.readFileSync(s,"utf-8")))}catch{i={}}let o={...i,...e};n.mkdirSync(N.dirname(s),{recursive:!0}),n.writeFileSync(s,JSON.stringify(o,null,2),"utf-8"),this.invalidate()}_parseConversationId(e){if(typeof e=="number"&&Number.isFinite(e))return e;if(typeof e=="string"&&e.trim()){let t=Number(e);if(Number.isFinite(t))return t}return null}_deriveHarnessApiBase(e){return(e||"").replace("/api/coding/","/api/harness/coding/")}getEndpoint(e){let t=this.get();return t.workspaceId&&t.apiBase?`${t.apiBase}/workspace/${t.workspaceId}/ide${e}`:t.apiBase?`${t.apiBase}${e}`:e}getHarnessEndpoint(e){let t=this.get(),n=t.harnessApiBase||this._deriveHarnessApiBase(t.apiBase);return t.workspaceId&&n?`${n}/workspace/${t.workspaceId}/ide${e}`:n?`${n}${e}`:e}getHeaders(){let e=this.get(),t={"Content-Type":"application/json"};return e.ideToken?(t["X-Vibe-IDE-Token"]=e.ideToken,t.Authorization=`Bearer ${e.ideToken}`):e.apiKey&&(t.Authorization=`Bearer ${e.apiKey}`),t}};function Oe(d){console.log("[RuijingAI] Extension activating...");let e=new V(d),t=new B(e),n=new z(e),s=new G(e,n),i=Y.chat.createChatParticipant("ruijing-ai.chat",s.handle.bind(s));i.iconPath=Y.Uri.joinPath(d.extensionUri,"icon.png"),i.followupProvider=s.getFollowupProvider(),d.subscriptions.push(i,n),n.loadModels(t).catch(o=>{console.warn("[RuijingAI] Failed to load models:",o)}),console.log("[RuijingAI] Extension activated successfully")}function Ne(){console.log("[RuijingAI] Extension deactivated")}0&&(module.exports={activate,deactivate});
//# sourceMappingURL=extension.js.map
