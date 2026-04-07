"use strict";var ke=Object.create;var J=Object.defineProperty;var Ee=Object.getOwnPropertyDescriptor;var Te=Object.getOwnPropertyNames;var Pe=Object.getPrototypeOf,be=Object.prototype.hasOwnProperty;var Se=(d,e)=>{for(var t in e)J(d,t,{get:e[t],enumerable:!0})},me=(d,e,t,n)=>{if(e&&typeof e=="object"||typeof e=="function")for(let s of Te(e))!be.call(d,s)&&s!==t&&J(d,s,{get:()=>e[s],enumerable:!(n=Ee(e,s))||n.enumerable});return d};var R=(d,e,t)=>(t=d!=null?ke(Pe(d)):{},me(e||!d||!d.__esModule?J(t,"default",{value:d,enumerable:!0}):t,d)),_e=d=>me(J({},"__esModule",{value:!0}),d);var et={};Se(et,{activate:()=>Qe,deactivate:()=>Ze});module.exports=_e(et);var U=R(require("vscode"));var L=R(require("vscode"));function Ie(d){return d.replace(/<think>[\s\S]*?<\/think>/gi,"")}function Me(d){return d.replace(/\[?\/?TOOL_CALL\]/gi,"").replace(/<minimax:tool_call>[\s\S]*?<\/minimax:tool_call>/gi,"").replace(/minimax:tool_call/gi,"").replace(/<\/?invoke[^>]*>/gi,"").replace(/\{"tool"\s*[=:>]+\s*"[^"]*"\s*,\s*"path"\s*[=:>]+\s*"[^"]*"\s*\}/g,"")}function K(d){return Me(Ie(d)).replace(/^\s*[\r\n]+/gm,"").trim()}var z=class d{buffer="";inTag=!1;tagType=null;static OPEN_PATTERNS=[{open:"<think>",close:"</think>",type:"think"},{open:"<minimax:tool_call>",close:"</minimax:tool_call>",type:"toolcall"}];push(e){this.buffer+=e;let t="";for(;this.buffer.length>0;){if(this.inTag&&this.tagType){let i=d.OPEN_PATTERNS.find(r=>r.type===this.tagType)?.close||"",o=this.buffer.indexOf(i);if(o===-1){this.buffer.length>1e4&&(this.buffer="",this.inTag=!1,this.tagType=null);break}this.buffer=this.buffer.slice(o+i.length),this.inTag=!1,this.tagType=null;continue}let n=-1,s=null;for(let i of d.OPEN_PATTERNS){let o=this.buffer.indexOf(i.open);o!==-1&&(n===-1||o<n)&&(n=o,s=i)}if(n===-1){let i=Math.max(0,this.buffer.length-30);t+=this.buffer.slice(0,i),this.buffer=this.buffer.slice(i);break}t+=this.buffer.slice(0,n),this.buffer=this.buffer.slice(n+s.open.length),this.inTag=!0,this.tagType=s.type}return t}flush(){let e=this.buffer;return this.buffer="",this.inTag=!1,this.tagType=null,this.inTag?"":e}};function pe(d){let e=d.match(/[A-Za-z0-9_\-./]+\.\w{1,8}/g)||[];return[...new Set(e)].filter(t=>!t.startsWith("http")&&t.includes("/")||t.includes("."))}function de(d){return/(修改|修复|改一下|改下|调整|fix|bug|创建|新增|开发|实现|搭建|编写|生成|写一个|写个|帮我写|做一个|做个|build|create|implement|develop|delete|删除|去掉|加上|加个|添加|增加|替换|改成|改为|加注释|写注释|加comment|重构|refactor|优化|整理|格式化|补充|完善|更新|升级|迁移|移动|重命名|rename|注释|comment|加一下|改一下|写一下|补一下)/i.test(d)}function ue(d){return/^(确认|应用|apply|yes|ok|接受|accept|好的|行|可以|没问题|开始|go|start|开始吧|开干|冲)/i.test(d.trim())}function ge(d){return/^(取消|拒绝|cancel|no|reject|算了|不要|不用了)/i.test(d.trim())}var H=class{constructor(e){this.config=e}async*stream(e){let{model:t,messages:n,maxTokens:s=4096,token:i}=e,o=this.config.getEndpoint("/chat/completions"),r=this.config.getHeaders(),c=JSON.stringify({model:t,messages:n,stream:!0,max_tokens:s,tool_choice:"none"}),a=new AbortController;i?.onCancellationRequested(()=>a.abort());let l=setTimeout(()=>a.abort(),12e4),m;try{m=await fetch(o,{method:"POST",headers:r,body:c,signal:a.signal})}catch(C){if(clearTimeout(l),C.name==="AbortError")return"";throw new Error(`LLM request failed: ${C.message}`)}if(clearTimeout(l),!m.ok){let C="";try{C=(await m.text()).slice(0,300)}catch{}throw new Error(`LLM API ${m.status}: ${C}`)}let f=m.body?.getReader();if(!f)try{let y=(await m.json())?.choices?.[0]?.message?.content||"";return yield y,y}catch{return""}let u=new TextDecoder,h=new z,S="",E="",T=Date.now(),g=(e.maxTokens??0)>4e3?45e3:(e.maxTokens??0)<500?15e3:3e4;try{for(;!i?.isCancellationRequested;){let C=Date.now()-T,y=Math.max(5e3,g-C),M=new Promise($=>setTimeout(()=>$({done:!0,timeout:!0}),y)),A=f.read(),j=await Promise.race([A,M]);if(j.timeout||j.done){j.done||(E+=u.decode());break}T=Date.now(),E+=u.decode(j.value,{stream:!0});let p=E.split(`
`);E=p.pop()||"";for(let $ of p){if(!$.startsWith("data: "))continue;let P=$.slice(6).trim();if(!(!P||P==="[DONE]"))try{let F=JSON.parse(P)?.choices?.[0]?.delta?.content;if(F){let W=h.push(F);W&&(S+=W,yield W)}}catch{}}}}finally{try{f.cancel()}catch{}}let x=h.flush();return x&&(S+=x,yield x),S}async complete(e){let t="";for await(let n of this.stream(e))t+=n;return t}async*streamCodingPipeline(e){let{message:t,selectedModel:n,conversationId:s,projectId:i,projectType:o,quickCreate:r=!1,token:c}=e,a=this.config.getHarnessEndpoint("/pipeline"),l=this.config.getHeaders(),m=JSON.stringify({message:t,selected_model:n||void 0,conversation_id:s??this.config.get().conversationId??void 0,project_id:i??void 0,project_type:o??void 0,quick_create:r}),f=new AbortController;c?.onCancellationRequested(()=>f.abort());let u=setTimeout(()=>f.abort(),3e5),h;try{h=await fetch(a,{method:"POST",headers:l,body:m,signal:f.signal})}catch(g){if(clearTimeout(u),g.name==="AbortError")return;throw new Error(`Coding pipeline request failed: ${g.message}`)}if(clearTimeout(u),!h.ok){let g="";try{g=(await h.text()).slice(0,500)}catch{}throw new Error(`Coding pipeline ${h.status}: ${g}`)}let S=h.body?.getReader();if(!S)return;let E=new TextDecoder,T="";try{for(;!c?.isCancellationRequested;){let g=await S.read();if(g.done)break;T+=E.decode(g.value,{stream:!0});let x=T.split(`

`);T=x.pop()||"";for(let C of x){let y=C.split(`
`),M="message",A=[];for(let p of y)p.startsWith("event:")?M=p.slice(6).trim():p.startsWith("data:")&&A.push(p.slice(5).trim());if(M==="ping")continue;let j=A.join(`
`).trim();if(!(!j||j==="[DONE]"))try{yield JSON.parse(j)}catch{}}}}finally{try{S.cancel()}catch{}}}async fetchModels(){try{let e=this.config.getEndpoint("/models"),t=await fetch(e,{headers:this.config.getHeaders()});if(!t.ok)return[];let n=await t.json();return n?.models||n?.data||[]}catch{return[]}}};var _=R(require("vscode"));var Ae="**/node_modules/**,**/dist/**,**/.git/**,**/*.zip,**/*.jar,**/*.war,**/target/**,**/build/**,**/.idea/**",$e=2600,Re=9e3,he=6e3,Le=24,je=48e3,Fe=3.5,Ne=60,De=3e5,ve=/\.(vue|js|jsx|ts|tsx|json|java|xml|yml|yaml|properties|scss|css|less|html)$/i,Oe=/(国际化|i18n|多语言|语言包|locale|翻译|文案)/i,Be=/(组件|widget|表单组件|form-component|render|渲染|upload|avatar|date|picker)/i,We=/(componentModelField|配置文件|配置项|config|widget\.config|editor\.config|字段类型|数据模型|STRING|DATE|字段绑定)/i,qe=/(检查|排查|看看|看一下|看一看|存不存在|缺失|缺少|不存在|有没有|是否存在|注册|入口|导入|导出|import|export|index\.js)/i,Ue=new Set(["src","form","component","widget","config","file","path","this","that","date","range","string","model","field","type","please","help","code"]),V=class{cache=null;dirty=!1;config=null;setConfig(e){this.config=e}markDirty(){this.dirty=!0}async build(e){let t=_.workspace.workspaceFolders;if(!t?.length)return"";let n=pe(e),s=this._buildCacheKey(n,e);if(this.cache&&!this.dirty&&this.cache.key===s&&Date.now()-this.cache.ts<De)return this.cache.text;try{let i=await this._buildContext(t[0],n,e);return this.cache={key:s,text:i,ts:Date.now()},this.dirty=!1,i}catch(i){return console.warn("[RuijingAI] contextBuilder failed",i),""}}async _buildContext(e,t,n){let i=(await _.workspace.findFiles(new _.RelativePattern(e,"**/*"),`{${Ae}}`,500)).map(p=>_.workspace.asRelativePath(p,!1)).sort(),o=Oe.test(n),r=Be.test(n),c=We.test(n),a=qe.test(n),l=_.window.visibleTextEditors.map(p=>_.workspace.asRelativePath(p.document.uri,!1)).filter(p=>!!p&&ve.test(p)&&!p.startsWith(".cursor/rules/")&&!p.startsWith(".claude/rules/")&&!/\.(md|mdc|txt)$/i.test(p)),m=this._extractSearchTerms(n,t,l),f=[],u=p=>{p&&!f.includes(p)&&f.push(p)};for(let p of t)for(let $ of this._expandMentionedPathCandidates(p)){let P=i.filter(k=>k.endsWith($)||k.includes($));for(let k of P.slice(0,4))u(k)}let h=i.filter(p=>ve.test(p)).map(p=>({rel:p,score:this._scorePath(p,m,{activeSourceFiles:l,isConfigTask:c,isI18nTask:o,isFormComponentTask:r})})).filter(p=>p.score>0).sort((p,$)=>$.score-p.score||p.rel.localeCompare($.rel));for(let p of h.slice(0,12))u(p.rel);for(let p of l)u(p);if(i.includes("src/apaas.json")){let p=["src/apaas.json","src/index.js","src/form-component/form-widget/index.js","src/form-component/form-editor/index.js","src/form-component/index.js","src/form-component-config/form-widget/index.js","src/form-component-config/form-editor/index.js","src/form-component-config/index.js"];for(let P of i)(P.endsWith(".widget.config.js")||P.endsWith(".editor.config.js"))&&(p.includes(P)||p.push(P));let $=p.filter(P=>i.includes(P)).sort((P,k)=>this._scorePath(k,m,{activeSourceFiles:l,isConfigTask:c,isI18nTask:o,isFormComponentTask:r})-this._scorePath(P,m,{activeSourceFiles:l,isConfigTask:c,isI18nTask:o,isFormComponentTask:r}));for(let P of $)u(P);if(o){let P=["src/form-component-local/index.js","src/form-component-local/zh-CN/index.js","src/form-component-local/en-US/index.js"];for(let k of P)i.includes(k)&&u(k)}if(a){let P=i.filter(k=>(k.endsWith("/index.js")||k.endsWith("/index.ts"))&&(k.includes("form-component")||k.includes("form-ability")||k==="src/index.js"));for(let k of P)u(k)}if(r||o){let k=i.filter(F=>/^src\/form-component\/form-widget\/(edit|ide|read|list|print|search|search-ide)\/.+\.vue$/.test(F)||/^src\/form-component\/form-editor\/.+\.vue$/.test(F)).sort((F,W)=>this._scorePath(W,m,{activeSourceFiles:l,isConfigTask:c,isI18nTask:o,isFormComponentTask:r})-this._scorePath(F,m,{activeSourceFiles:l,isConfigTask:c,isI18nTask:o,isFormComponentTask:r}));for(let F of k)u(F)}}let E=["src/index.js","src/index.ts","src/main.ts","src/App.vue","package.json","pom.xml"];for(let p of E)i.includes(p)&&u(p);let T=[],g=0;for(let p of f.slice(0,Le)){if(g>je)break;try{let $=_.Uri.joinPath(e.uri,p),P=await _.workspace.fs.readFile($),k=Buffer.from(P).toString("utf-8"),W=p.endsWith(".widget.config.js")||p.endsWith(".editor.config.js")||p.endsWith("apaas.json")||p.includes("/form-component-local/")||a&&(p.endsWith("/index.js")||p.endsWith("/index.ts"))?Re:$e;k.length>W&&(k=k.slice(0,W)+`
/* ... truncated ... */`),T.push(`### ${p}
\`\`\`
${k}
\`\`\``),g+=k.length}catch{}}let x=await this._querySymbolIndex(m,e),C=await this._loadSkills(e,n),y=i.slice(0,Ne).join(`
`),A=`${m.length?`SEARCH_TERMS:
${m.join(", ")}

`:""}RELEVANT_FILE_CONTENTS:
${T.join(`

`)}${x}

WORKSPACE_FILE_INDEX(${i.length}):
${y}${C}`,j=Math.ceil(A.length/Fe);return j>2e4&&console.warn(`[ContextBuilder] Large context: ~${j} tokens (${A.length} chars). Consider reducing file count.`),A}_buildCacheKey(e,t){let n=t.toLowerCase().replace(/\s+/g," ").trim().slice(0,240);return`${e.slice().sort().join(",")}|${n}`}_expandMentionedPathCandidates(e){let t=e.replace(/:\\d+$/g,"").replace(/\\/g,"/"),n=new Set([t]),s=[".umd.min.js",".umd.js",".common.js",".css"];for(let o of s)t.endsWith(o)&&n.add(t.slice(0,-o.length));let i=t.split("/").pop()||t;return n.add(i),[...n].filter(Boolean)}_extractSearchTerms(e,t,n){let s=new Set,i=e||"";for(let c of t)for(let a of this._expandMentionedPathCandidates(c))a.split(/[\\/._-]+/).filter(Boolean).forEach(l=>s.add(l.toLowerCase())),s.add(a.toLowerCase());for(let c of n.slice(0,3))(c.split("/").pop()||c).replace(/\.(vue|js|jsx|ts|tsx|json)$/i,"").split(/[._-]+/).filter(Boolean).forEach(l=>s.add(l.toLowerCase()));let o=i.match(/[A-Za-z][A-Za-z0-9_-]{2,}/g)||[];for(let c of o){let a=c.toLowerCase();Ue.has(a)||s.add(a)}return[...s].filter(c=>c.length>=3).sort((c,a)=>a.length-c.length).slice(0,12)}_scorePath(e,t,n){let s=e.toLowerCase(),i=0;n.activeSourceFiles.includes(e)&&(i+=220),n.isConfigTask&&(s.endsWith(".widget.config.js")||s.endsWith(".editor.config.js"))&&(i+=260),n.isConfigTask&&s.includes("/form-component-config/")&&(i+=180),n.isI18nTask&&s.includes("/form-component-local/")&&(i+=220),n.isFormComponentTask&&s.includes("/form-component/")&&(i+=80),n.isFormComponentTask&&s.includes("/form-widget/")&&(i+=90),n.isFormComponentTask&&s.includes("/form-editor/")&&(i+=70);for(let o of t)o&&(s===o?i+=240:s.endsWith(`/${o}`)?i+=180:s.includes(o)&&(i+=o.length>=10?110:55));return i}async _querySymbolIndex(e,t){if(!this.config||!e.length)return"";let n=this.config.get();if(!n.workspaceId||!n.apiBase)return"";let s=e.filter(a=>/^[a-zA-Z]\w{2,}$/.test(a)).slice(0,5);if(!s.length)return"";let i=[],o=0,r=this.config.getHeaders(),c=await Promise.allSettled(s.map(async a=>{let l=this.config.getEndpoint(`/symbols?q=${encodeURIComponent(a)}&limit=5`),m=await fetch(l,{headers:r,signal:AbortSignal.timeout(5e3)});return m.ok?((await m.json())?.symbols||[]).slice(0,3):[]}));for(let a of c){if(o>=he)break;if(!(a.status!=="fulfilled"||!a.value.length))for(let l of a.value){if(o>=he)break;try{let m=_.Uri.joinPath(t.uri,l.file),f=await _.workspace.fs.readFile(m),u=Buffer.from(f).toString("utf-8").split(`
`),h=Math.max(0,l.line-51),S=Math.min(u.length,l.line+50),E=u.slice(h,S).join(`
`);if(E.length>0){let T=`### SYMBOL: ${l.name} @ ${l.file}:${l.line}
\`\`\`
${E.slice(0,2e3)}
\`\`\``;i.push(T),o+=T.length}}catch{}}}return i.length?`

SYMBOL_INDEXED_CONTEXT:
${i.join(`

`)}`:""}async _loadSkills(e,t){try{let n=new _.RelativePattern(e,".claude/skills/*.skill.md"),s=await _.workspace.findFiles(n,void 0,10);if(!s.length)return"";let i=[];for(let o of s.slice(0,2))try{let r=await _.workspace.fs.readFile(o),c=Buffer.from(r).toString("utf-8"),a=_.workspace.asRelativePath(o,!1);i.push(`### SKILL: ${a}
${c.slice(0,4e3)}`)}catch{}return i.length?`

SKILL_GUIDES:
${i.join(`

`)}`:""}catch{return""}}};var N=R(require("vscode")),He=[{path:"CLAUDE.md",maxLen:5e3,label:"PROJECT_GUIDE"},{path:"memory.md",maxLen:2e3,label:"MEMORY"},{path:".claude/rules/coding-style.rule.md",maxLen:6e3,label:"RULE"},{path:".claude/rules/mpaas-query-reference.rule.md",maxLen:5e3,label:"RULE"},{path:".claude/rules/dev-workflow.rule.md",maxLen:3e3,label:"RULE"}],Ke=[".cursor/rules/**/*.mdc",".cursor/rules/**/*.md",".claude/rules/**/*.md",".claude/rules/**/*.rule.md"],we=8,Ge=6e3,Ce=35e3,Y=4e4,Xe=3e5,Q=class{cache=null;invalidate(){this.cache=null}async load(){if(this.cache&&Date.now()-this.cache.ts<Xe)return this.cache.text;let e=N.workspace.workspaceFolders;if(!e?.length)return"";let t=e[0],n=[],s=new Set;for(let o of He)try{let r=N.Uri.joinPath(t.uri,o.path),c=await N.workspace.fs.readFile(r),a=Buffer.from(c).toString("utf-8");a.trim()&&(n.push(`## ${o.label}: ${o.path}
${a.slice(0,o.maxLen)}`),s.add(o.path))}catch{}for(let o of Ke)try{let r=await N.workspace.findFiles(new N.RelativePattern(t,o),void 0,we);for(let c of r){let a=N.workspace.asRelativePath(c,!1);if(!s.has(a)){if(n.length>=we)break;try{let l=await N.workspace.fs.readFile(c),m=Buffer.from(l).toString("utf-8"),f=m.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/),u=!1;if(f){let h=f[1];m=f[2],u=/alwaysApply:\s*true/i.test(h)}if(m.trim()){let h=u?Ce:Ge;n.push(`## RULE: ${a}
${m.slice(0,h)}`),s.add(a)}}catch{}}}}catch{}let i=n.join(`

`);if(i.length>Y&&n.length>1){for(;i.length>Y&&n.length>1&&n[n.length-1].length<Ce/2;){n.pop();i=n.join(`

`)}i.length>Y&&(i=i.slice(0,Y))}return this.cache={text:i,ts:Date.now()},console.log(`[RuijingAI] guidesLoader: loaded ${n.length} guide/rule files, total ${i.length} chars`),i}};function ye(d,e){let t=fe(d);if(t.edits.length>0)return{type:"edits",edits:t.edits,summary:t.summary};let n=ze(d);if(n.files.length>0)return{type:"plan",plan:n};if(e){let s=Je(d,e);if(s.length>0)return{type:"edits",edits:s,summary:""}}return{type:"chat"}}function Je(d,e){let t=/```[\w]*\n([\s\S]*?)```/g,n,s=[];for(;(n=t.exec(d))!==null;){let i=n[1];if(i.split(`
`).length<10)continue;[/^<template>/m,/^<script/m,/^import\s/m,/^export\s+(default|class|function|const)/m,/^package\s+\w/m,/^(public|private)\s+(class|interface)/m,/^#(include|import|pragma)/m,/^(def|class)\s+\w/m].some(c=>c.test(i))&&s.push(i)}return s.length===1?[{path:e,content:s[0],action:"write"}]:[]}function fe(d){let e=[],t="",n=d.match(/^##\s*(?:总结|Summary|概要|Result|Changes|修改总结)[：:]\s*(.+)/m);n&&(t=n[1].trim());let s=/FILE:\s*([^\n]+)\s*\n\s*```[\w]*\n([\s\S]*?)```/g,i;for(;(i=s.exec(d))!==null;){let o=i[1].trim().replace(/^[`'"]+|[`'"]+$/g,"").replace(/^\/+/,""),r=i[2];o&&r&&!o.includes("..")&&e.push({path:o,content:r,action:"write"})}return{edits:e,summary:t}}function ze(d){let e=[],t="",n=d.match(/^##\s*(?:实现方案|计划|Plan|Implementation|Steps|Proposal|Approach|方案)[：:]\s*(.+)/m);n&&(t=n[1].trim());let s=/^\s*\d+\.\s*`([^`]+)`\s*[—\-–]\s*(.+)/gm,i;for(;(i=s.exec(d))!==null;){let o=i[1].trim().replace(/^\/+/,""),r=i[2].trim();o&&r&&e.push({path:o,description:r})}return{summary:t,files:e}}var D=R(require("vscode")),Z=class{async apply(e){let t=D.workspace.workspaceFolders;if(!t?.length)return{applied:[],skipped:[{path:"",reason:"No workspace folder"}]};let n=t[0].uri,s=[],i=[];for(let o of e.slice(0,12)){let r=o.path.trim().replace(/\\/g,"/").replace(/^\/+/,"");if(!r||r.includes("..")){i.push({path:r||"(empty)",reason:"Invalid path"});continue}if(o.action==="delete"){try{let c=D.Uri.joinPath(n,r);await D.workspace.fs.delete(c,{recursive:!0}),s.push({path:r,action:"delete"})}catch(c){i.push({path:r,reason:c.message||"Delete failed"})}continue}if(!o.content){i.push({path:r,reason:"Missing content"});continue}try{let c=D.Uri.joinPath(n,r),a=new D.WorkspaceEdit,l=Buffer.from(o.content,"utf-8");a.createFile(c,{overwrite:!0,ignoreIfExists:!1,contents:l}),await D.workspace.applyEdit(a)?s.push({path:r,action:o.action}):i.push({path:r,reason:"applyEdit returned false"})}catch(c){i.push({path:r,reason:c.message||"Write failed"})}}return{applied:s,skipped:i}}};var ee=class{constructor(e,t,n,s){this.llmClient=e;this.fileWriter=t;this.contextBuilder=n;this.guidesLoader=s}pendingPlan=null;hasPending(){return this.pendingPlan!==null}store(e){this.pendingPlan=e}clear(){this.pendingPlan=null}getPending(){return this.pendingPlan}async execute(e,t,n,s){this.pendingPlan=null;let i=[],o=[],r=[],c=await this.contextBuilder.build(e.userMsg||""),a=await this.guidesLoader.load();for(let f=0;f<e.files.length&&!s.isCancellationRequested;f++){let u=e.files[f];n.progress(`\u751F\u6210\u4E2D (${f+1}/${e.files.length}) ${u.path}`),n.markdown(`
\u23F3 **\u751F\u6210\u4E2D (${f+1}/${e.files.length})** \`${u.path}\`...
`);let h=e.files.filter((y,M)=>M!==f).map(y=>`- \`${y.path}\` \u2014 ${y.description}`).join(`
`),S=r.map(y=>`### ${y.path}
\`\`\`
${y.excerpt}
\`\`\``).join(`
`),E=this._getFileRoleHint(u.path),g=[{role:"system",content:["\u4F60\u662F IDE \u4EE3\u7801\u4FEE\u6539\u4EE3\u7406\u3002\u73B0\u5728\u6309\u7167\u5DF2\u786E\u8BA4\u7684\u8BA1\u5212\u9010\u6587\u4EF6\u751F\u6210\u4EE3\u7801\u3002",`\u5F53\u524D\u4EFB\u52A1\uFF1A\u751F\u6210 FILE: ${u.path}`,`\u6587\u4EF6\u63CF\u8FF0\uFF1A${u.description}`,E?`\u6587\u4EF6\u89D2\u8272\u63D0\u793A\uFF1A${E}`:"",`
\u6574\u4F53\u8BA1\u5212\uFF1A${e.summary}`,`\u5176\u4ED6\u6587\u4EF6\uFF1A
${h}`,S?`
\u5DF2\u751F\u6210\u7684\u6587\u4EF6\uFF08\u4F9B\u53C2\u8003\u63A5\u53E3/\u7C7B\u540D\uFF09\uFF1A
${S}`:"",`
\u8F93\u51FA\u683C\u5F0F\uFF1A\u53EA\u8F93\u51FA\u8FD9\u4E00\u4E2A\u6587\u4EF6\u3002\u5148\u5199 FILE: \u8DEF\u5F84\uFF0C\u7136\u540E\u7D27\u8DDF\u5B8C\u6574\u4EE3\u7801\u5757\u3002\u4EE3\u7801\u5FC5\u987B\u5B8C\u6574\uFF0C\u4E0D\u8981\u7701\u7565\u4EFB\u4F55\u90E8\u5206\u3002`,a?`
PROJECT_RULES:
${a}`:""].filter(Boolean).join(`
`)}];c?g.push({role:"user",content:`\u5F53\u524D\u5DE5\u4F5C\u533A\u4EE3\u7801\uFF1A
${c.slice(0,5e3)}

---
\u8BF7\u751F\u6210 ${u.path}`}):g.push({role:"user",content:`\u8BF7\u751F\u6210 ${u.path}\uFF1A${u.description}

\u539F\u59CB\u9700\u6C42\uFF1A${e.userMsg||""}`});let x="";try{for await(let y of this.llmClient.stream({model:t,messages:g,maxTokens:8192,token:s}))x+=y,n.markdown(y)}catch(y){o.push({path:u.path,reason:y.message||"LLM error"}),n.markdown(`
\u26A0\uFE0F \`${u.path}\` \u751F\u6210\u5931\u8D25: ${y.message}
`);continue}let C=fe(x);if(C.edits.length>0){let y=await this.fileWriter.apply(C.edits);i.push(...y.applied.map(M=>M.path)),o.push(...y.skipped);for(let M of C.edits){let A=M.content.split(`
`);r.push({path:M.path,excerpt:A.slice(0,50).join(`
`)})}n.markdown(`
\u2705 \`${u.path}\` \u5DF2\u5199\u5165
`),this.contextBuilder.markDirty()}else o.push({path:u.path,reason:"\u672A\u89E3\u6790\u5230\u6587\u4EF6\u5185\u5BB9"}),n.markdown(`
\u26A0\uFE0F \`${u.path}\` \u89E3\u6790\u5931\u8D25\uFF0C\u8DF3\u8FC7
`)}let l=i.map(f=>`- \u2705 ${f}`).join(`
`),m=o.map(f=>`- \u274C ${f.path}: ${f.reason}`).join(`
`);n.markdown(`
---
**\u5168\u90E8\u5B8C\u6210 (${i.length}/${e.files.length})**`+(l?`

\u5DF2\u5199\u5165\uFF1A
${l}`:"")+(m?`

\u672A\u6210\u529F\uFF1A
${m}`:"")+`
`)}_getFileRoleHint(e){if(e.endsWith(".widget.config.js"))return"\u8FD9\u662F\u7EC4\u4EF6\u914D\u7F6E\u6587\u4EF6\u3002\u4E25\u683C\u9075\u5FAA PROJECT_RULES \u4E2D\u7684 widget config \u7ED3\u6784\uFF1Aversion, code, desc, instance, component(\u6240\u6709\u6E32\u67D3\u6A21\u5F0F), widget(display/allow/default/validator/special/editor), componentModelField, client.mobile\u3002";let t=e.match(/form-widget\/(ide|edit|read|list|print|search|search-ide)\//);if(t){let n=t[1];return`\u8FD9\u662F ${n} \u6E32\u67D3\u6A21\u5F0F\u7EC4\u4EF6\u3002\u4F7F\u7528: ${{ide:"FormWidgetMixin (@/mixin/form-widget.mixin)",edit:"FormWidgetMixin (@/mixin/form-widget.mixin)",read:"FormWidgetMixin (@/mixin/form-widget.mixin)",list:"\u65E0mixin\uFF0C\u4F7F\u7528 inject:['listEngine'] + props:['componentConfig','formValue','propKey']",print:"PrintWidgetMixin (@/mixin/print-widget.mixin)",search:"SearchWidgetMixin (@/mixin/search-widget.mixin)","search-ide":"SearchIdeWidgetMixin (@/mixin/search-ide-widget.mixin)"}[n]||"\u53C2\u8003 PROJECT_RULES"}\u3002\u53C2\u8003 PROJECT_RULES \u4E2D\u7684\u540C\u6A21\u5F0F\u7EC4\u4EF6\u793A\u4F8B\u3002`}return e.endsWith(".editor.config.js")?"\u8FD9\u662F\u7F16\u8F91\u5668\u914D\u7F6E\u6587\u4EF6\u3002\u5FC5\u987B\u5305\u542B code, editorConfigType, componentName, configProperty \u56DB\u4E2A\u5B57\u6BB5\u3002":/form-editor\/.*\.vue$/.test(e)?"\u8FD9\u662F\u8868\u5355\u8BBE\u8BA1\u5668\u53F3\u4FA7\u5C5E\u6027\u9762\u677F\u7EC4\u4EF6\u3002\u4F7F\u7528 EditorFormConfigMixin (@/mixin/form-config.mixin)\u3002":e==="src/apaas.json"?"\u5E73\u53F0\u5143\u6570\u636E\u6587\u4EF6\u3002\u4FDD\u7559\u5DF2\u6709\u5185\u5BB9\uFF0C\u53EA\u6DFB\u52A0/\u4FEE\u6539\u5F53\u524D\u7EC4\u4EF6\u7684\u6761\u76EE\u3002\u6CE8\u610F type \u5B57\u6BB5\u8981\u4E0E widget config \u7684 code \u4E00\u81F4\u3002":/\/index\.js$/.test(e)?"\u805A\u5408\u5BFC\u51FA\u6587\u4EF6\u3002\u5BFC\u5165\u5E76\u5BFC\u51FA\u65B0\u7EC4\u4EF6\uFF0C\u4FDD\u7559\u5DF2\u6709\u7684\u5BFC\u5165\u4E0D\u8981\u5220\u9664\u3002":""}};var xe=`\u4F60\u662F\u96C6\u6210\u5728 VS Code \u98CE\u683C IDE \u91CC\u7684\u4E2D\u6587\u7F16\u7A0B\u52A9\u624B\u3002\u4F60\u53EF\u4EE5\u56DE\u7B54\u95EE\u9898\uFF0C\u4E5F\u53EF\u4EE5\u76F4\u63A5\u4FEE\u6539\u4EE3\u7801\u6587\u4EF6\u3002

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
- \u5982\u679C\u5F53\u524D\u770B\u5230\u7684\u662F \`.umd.js\`\u3001\`.common.js\`\u3001\`.min.js\`\u3001\`dist/\`\u3001\`build/\` \u4E4B\u7C7B\u6784\u5EFA\u4EA7\u7269\uFF0C\u8BF7\u4F18\u5148\u56DE\u6EAF \`src/\` \u4E0B\u6E90\u7801\u548C\u914D\u7F6E\u6587\u4EF6\uFF0C\u4E0D\u8981\u628A\u6784\u5EFA\u4EA7\u7269\u5F53\u6210\u552F\u4E00\u7F16\u8F91\u76EE\u6807`,te=class{constructor(e,t){this.config=e;this.modelSelector=t;this.llmClient=new H(e),this.contextBuilder=new V,this.contextBuilder.setConfig(e),this.guidesLoader=new Q,this.fileWriter=new Z,this.planMode=new ee(this.llmClient,this.fileWriter,this.contextBuilder,this.guidesLoader)}llmClient;contextBuilder;guidesLoader;fileWriter;planMode;modelsLoaded=!1;externalHistoryNoticeShown=new Set;async handle(e,t,n,s){this.modelsLoaded||(this.modelsLoaded=!0,this.modelSelector.loadModels(this.llmClient).catch(()=>{}));let i=e.prompt.trim();if(!i)return n.markdown("\u8BF7\u8F93\u5165\u60A8\u7684\u95EE\u9898\u6216\u9700\u6C42\u3002"),{};if(this._canUseCodingPipeline()){this.planMode.hasPending()&&this.planMode.clear();try{return this._announceExternalHistoryContext(t,n),await this._handleViaCodingPipeline(i,n,s),{}}catch(o){console.warn("[RuijingAI] coding pipeline fallback to legacy mode",o),n.markdown(`

\u26A0\uFE0F \u7EDF\u4E00 Coding Runtime \u6682\u65F6\u4E0D\u53EF\u7528\uFF0C\u5DF2\u56DE\u9000\u5230\u672C\u5730\u517C\u5BB9\u6A21\u5F0F\u3002
`)}}try{if(this.planMode.hasPending()){if(ue(i)){let g=this.planMode.getPending(),x=this.modelSelector.resolve(!0);return n.markdown(`\u{1F4CB} \u8BA1\u5212\u5DF2\u786E\u8BA4\uFF0C\u5F00\u59CB\u9010\u6587\u4EF6\u751F\u6210...
`),await this.planMode.execute(g,x,n,s),{}}if(ge(i))return this.planMode.clear(),n.markdown("\u5DF2\u53D6\u6D88\u8BA1\u5212\uFF0C\u6587\u4EF6\u672A\u53D8\u52A8\u3002"),{};this.planMode.clear()}let[o,r]=await Promise.all([this.contextBuilder.build(i),this.guidesLoader.load()]),c=de(i),a=this.modelSelector.resolve(c),l=i,m=L.window.activeTextEditor,f=m?L.workspace.asRelativePath(m.document.uri,!1):void 0,u=f?this._isGeneratedArtifact(f):!1;if(c&&f&&!this._mentionsSpecificFile(i)&&this._shouldScopeToActiveFile(f)){let g="";m&&(g=m.document.getText(),g.length>8e3&&(g=g.slice(0,8e3)+`
/* ... truncated ... */`)),l=`${i}

\u8BF7\u53EA\u9488\u5BF9\u5F53\u524D\u6253\u5F00\u7684\u6587\u4EF6\u64CD\u4F5C: ${f}

\u5F53\u524D\u6587\u4EF6\u5B8C\u6574\u5185\u5BB9:
\`\`\`
${g}
\`\`\``}else c&&!this._mentionsSpecificFile(i)&&(l=`${i}

\u8BF7\u5148\u6839\u636E\u5F53\u524D\u5DE5\u4F5C\u533A\u5DF2\u6709\u6E90\u7801\u548C\u89C4\u5219\u6587\u4EF6\uFF0C\u81EA\u4E3B\u5B9A\u4F4D\u6700\u76F8\u5173\u7684\u5B9E\u73B0\u6587\u4EF6\u4E0E\u56FD\u9645\u5316\u6587\u4EF6\uFF1B\u9664\u975E\u5DE5\u4F5C\u533A\u4E2D\u786E\u5B9E\u4E0D\u5B58\u5728\uFF0C\u5426\u5219\u4E0D\u8981\u8981\u6C42\u7528\u6237\u624B\u52A8\u63D0\u4F9B\u6587\u4EF6\u5185\u5BB9\u3002${u?`

\u6CE8\u610F\uFF1A\u5F53\u524D\u6FC0\u6D3B\u6587\u4EF6\u770B\u8D77\u6765\u662F\u6784\u5EFA\u4EA7\u7269\u6216\u6253\u5305\u8F93\u51FA\uFF0C\u8BF7\u4E0D\u8981\u56F4\u7ED5\u5B83\u5B9A\u4F4D\uFF0C\u4F18\u5148\u5BFB\u627E src/ \u4E0B\u7684\u6E90\u7801\u3001\u914D\u7F6E\u6587\u4EF6\u548C\u8BED\u8A00\u5305\u3002`:""}`);let h=this._buildMessages(l,o,r,t),S=r.length>1e4?8192:4096,E="";for await(let g of this.llmClient.stream({model:a,messages:h,maxTokens:S,token:s}))E+=g,n.markdown(g);if(!E)return n.markdown("\u6A21\u578B\u672A\u8FD4\u56DE\u5185\u5BB9\uFF0C\u8BF7\u91CD\u8BD5\u3002"),{};let T=ye(E,f);if(T.type==="edits"){let g=await this.fileWriter.apply(T.edits);this.contextBuilder.markDirty();let x=g.applied.map(y=>`- \u2705 ${y.path}`).join(`
`),C=g.skipped.map(y=>`- \u274C ${y.path}: ${y.reason}`).join(`
`);(x||C)&&n.markdown(`

---
**\u6587\u4EF6\u64CD\u4F5C\u7ED3\u679C\uFF1A**`+(x?`
${x}`:"")+(C?`
${C}`:"")+`
`)}else T.type==="plan"&&(T.plan.userMsg=i,this.planMode.store(T.plan),n.markdown(`

---
\u8F93\u5165 **\u786E\u8BA4** \u5F00\u59CB\u9010\u6587\u4EF6\u751F\u6210\u4EE3\u7801\uFF0C\u6216 **\u53D6\u6D88** \u653E\u5F03\u3002\u4E5F\u53EF\u4EE5\u56DE\u590D\u8C03\u6574\u8981\u6C42\u3002
`));return{}}catch(o){return console.error("[RuijingAI] handler error",o),n.markdown(`

\u274C \u9519\u8BEF: ${o.message||"\u672A\u77E5\u9519\u8BEF"}`),{}}}getFollowupProvider(){return{provideFollowups:(e,t,n)=>this.planMode.hasPending()?[{prompt:"\u786E\u8BA4",label:"\u2705 \u786E\u8BA4\u5F00\u59CB\u751F\u6210"},{prompt:"\u53D6\u6D88",label:"\u274C \u53D6\u6D88\u8BA1\u5212"}]:[]}}_canUseCodingPipeline(){let e=this.config.get();return!!(e.workspaceId&&e.ideToken&&(e.harnessApiBase||e.apiBase))}_buildPipelineMessage(e){let t=L.window.activeTextEditor,n=t?L.workspace.asRelativePath(t.document.uri,!1):"";return n?this._isGeneratedArtifact(n)?`${e}

\u8865\u5145\u4E0A\u4E0B\u6587\uFF1A\u5F53\u524D\u6FC0\u6D3B\u6587\u4EF6\u662F\u6784\u5EFA\u4EA7\u7269 ${n}\uFF0C\u8BF7\u4F18\u5148\u68C0\u67E5 src/ \u4E0B\u6E90\u7801\u3001\u914D\u7F6E\u6587\u4EF6\u548C\u5165\u53E3\u6587\u4EF6\uFF0C\u4E0D\u8981\u56F4\u7ED5\u6784\u5EFA\u4EA7\u7269\u4FEE\u6539\u3002`:`${e}

\u8865\u5145\u4E0A\u4E0B\u6587\uFF1A\u5F53\u524D\u6253\u5F00\u6587\u4EF6\u4E3A ${n}\u3002\u5982\u679C\u672C\u6B21\u9700\u6C42\u4E0E\u5B83\u76F8\u5173\uFF0C\u8BF7\u4F18\u5148\u68C0\u67E5\u5B83\u4EE5\u53CA\u76F8\u90BB\u7684\u6E90\u7801\u3001\u914D\u7F6E\u548C\u5165\u53E3\u6587\u4EF6\u3002`:e}async _handleViaCodingPipeline(e,t,n){let s=de(e),i=this.modelSelector.resolve(s),o=this._buildPipelineMessage(e),r=!1,c=!1,a=!1;for await(let l of this.llmClient.streamCodingPipeline({message:o,selectedModel:i,conversationId:this.config.get().conversationId,token:n})){let m=l?.type||"";if(m==="step"){let f=l.step||"",u=l.status||"",h=this._formatPipelineStep(f,u,l.data||{});h&&(c=!0,t.markdown(h));continue}if(m==="content"){let f=K(String(l.content||""));f.trim()&&(c=!0,a=!0,t.markdown(f));continue}if(m==="agent_thinking_delta"){let f=K(String(l.content||""));f&&(r=!0,c=!0,a=!0,t.markdown(f));continue}if(m==="agent_thinking"){if(r)continue;let f=K(String(l.content||""));f.trim()&&(c=!0,a=!0,t.markdown(f));continue}if(m==="agent_tool"){let f=l.tool_display||l.tool||"\u5DE5\u5177",u=String(l.input_preview||"").trim();c=!0,t.markdown(u?`

\u{1F527} **${f}** \`${u}\`
`:`

\u{1F527} **${f}**
`);continue}if(m==="agent_result"){let f=String(l.output_preview||"").trim();f&&(c=!0,t.markdown(l.is_error?`
> \u274C ${f}

`:`
> \u2705 ${f}

`));continue}if(m==="agent_done"){let f=K(String(l.result||""));f.trim()&&f.trim().toLowerCase()!=="completed"&&!a&&(c=!0,a=!0,t.markdown(`

${f}
`));continue}if(m==="agent_error"||m==="error")throw new Error(l.message||"Coding pipeline failed");if(m==="scene_detected"||m==="done"){l.conversation_id&&await this.config.updateWorkspaceConfig({conversationId:Number(l.conversation_id)});continue}}c||t.markdown("\u5DF2\u5904\u7406\u5B8C\u6210\u3002")}_formatPipelineStep(e,t,n){return e==="detect_scene"&&t==="running"?`

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
`:""}_buildMessages(e,t,n,s){let o=[{role:"system",content:[xe,t?`
WORKSPACE_CONTEXT:
${t.slice(0,18e3)}`:"",n?`
PROJECT_RULES:
${n}`:""].filter(Boolean).join(`
`)}];if(s.history.length>0){for(let a of s.history.slice(-6))if(a instanceof L.ChatRequestTurn)o.push({role:"user",content:a.prompt.slice(0,1500)});else if(a instanceof L.ChatResponseTurn){let l="";for(let m of a.response)m instanceof L.ChatResponseMarkdownPart&&(l+=m.value.value);l&&o.push({role:"assistant",content:l.slice(0,2e3)})}}else{let a=this._loadExternalChatHistoryPayload();if(a.messages.length>0){o.push({role:"system",content:"\u4EE5\u4E0B\u662F\u7528\u6237\u5728 AI Coding \u5BF9\u8BDD\u4E2D\u7684\u5386\u53F2\u8BB0\u5F55\uFF08\u6765\u81EA Web \u7AEF\uFF09\uFF0C\u8BF7\u7ED3\u5408\u8FD9\u4E9B\u4E0A\u4E0B\u6587\u56DE\u7B54\uFF1A"});for(let l of a.messages.slice(-8))o.push({role:l.role,content:l.content.slice(0,2e3)})}}o.push({role:"user",content:e});let c=o.reduce((a,l)=>a+l.content.length,0);if(c>8e4){let a=c-8e4,l=Math.max(4e3,18e3-a);o[0]={role:"system",content:[xe,t?`
WORKSPACE_CONTEXT (trimmed):
${t.slice(0,l)}`:"",n?`
PROJECT_RULES:
${n}`:""].filter(Boolean).join(`
`)}}return o}_announceExternalHistoryContext(e,t){if(e.history.length>0)return;let n=this._loadExternalChatHistoryPayload();if(!n.messages.length)return;let s=this._getExternalHistoryNoticeKey();this.externalHistoryNoticeShown.has(s)||(this.externalHistoryNoticeShown.add(s),t.markdown(`

\u2139\uFE0F \u5DF2\u52A0\u8F7D\u5F53\u524D\u5DE5\u4F5C\u533A\u6700\u8FD1 ${n.messages.length} \u6761 AI Coding \u5386\u53F2\u4F5C\u4E3A\u4E0A\u4E0B\u6587\u3002\u53D7 IDE \u539F\u751F\u804A\u5929\u9762\u677F\u9650\u5236\uFF0C\u65E7\u6D88\u606F\u4E0D\u4F1A\u81EA\u52A8\u56DE\u653E\u663E\u793A\u5728\u8FD9\u91CC\u3002

`))}_getExternalHistoryNoticeKey(){let e=this.config.get();return e.workspaceId?e.workspaceId:L.workspace.workspaceFolders?.[0]?.uri.fsPath||"default"}_loadExternalChatHistoryPayload(){try{let e=L.workspace.workspaceFolders;if(!e?.length)return{conversationId:null,messages:[]};let t=require("path"),n=require("fs"),s=t.join(e[0].uri.fsPath,".vscode","chat-history.json");if(!n.existsSync(s))return{conversationId:null,messages:[]};let i=JSON.parse(n.readFileSync(s,"utf-8"));if(Array.isArray(i?.messages))return{conversationId:Number.isFinite(Number(i.conversation_id))?Number(i.conversation_id):null,messages:i.messages.filter(o=>o.role&&o.content)}}catch{}return{conversationId:null,messages:[]}}_mentionsSpecificFile(e){return/[A-Za-z0-9_\-]+\.\w{1,6}/.test(e)||/\bsrc\//.test(e)}_shouldScopeToActiveFile(e){let t=e.replace(/\\/g,"/");return/^\.cursor\/rules\//.test(t)||/^\.claude\/rules\//.test(t)||this._isGeneratedArtifact(t)||/\.(md|mdc|txt)$/i.test(t)?!1:/\.(vue|js|jsx|ts|tsx|json|java|xml|yml|yaml|properties|scss|css|less|html)$/i.test(t)}_isGeneratedArtifact(e){let t=e.replace(/\\/g,"/").toLowerCase();return/(^|\/)(dist|build|coverage|out|target|tmp|temp)\//.test(t)||/(^|\/)public\//.test(t)&&!t.startsWith("src/")?!0:/\.(umd(\.min)?|common|min|bundle)\.js$/i.test(t)}};var O=R(require("vscode")),ne=class d{constructor(e){this.config=e;this.statusBarItem=O.window.createStatusBarItem(O.StatusBarAlignment.Right,100),this.statusBarItem.command="ruijing-ai.selectModel",this.statusBarItem.tooltip="\u777F\u9CB8AI: \u9009\u62E9\u6A21\u578B",this.updateLabel(),this.statusBarItem.show();let t=O.commands.registerCommand("ruijing-ai.selectModel",()=>this.showPicker());this.disposables.push(t,this.statusBarItem)}statusBarItem;models=[];selectedModel=null;autoMode=!0;disposables=[];static EDIT_MODELS=["claude-sonnet-4-6","claude-sonnet-4","gpt-5.4","gpt-4o"];static CHAT_MODELS=["qwen3-coder-next","qwen-plus","gpt-5.4","MiniMax-M2.7"];resolve(e){let t=this.config.get();if(!this.autoMode&&this.selectedModel)return this.selectedModel;let n=e?d.EDIT_MODELS:d.CHAT_MODELS;for(let i of n){let o=this.findModelByNeedle(i);if(o)return o.id}let s=this.findModelByNeedle(t.model);return s?s.id:t.model||"MiniMax-M2.7"}async loadModels(e){this.models=await e.fetchModels(),this.autoMode=this.config.get().autoMode,this.updateLabel()}updateLabel(){if(this.autoMode)this.statusBarItem.text="$(sparkle) Auto";else{let t=(this.findModelByNeedle(this.selectedModel||this.config.get().model)?.name||this.selectedModel||this.config.get().model).replace(/^claude-/,"").replace(/^gpt-/,"GPT-").slice(0,15);this.statusBarItem.text=`$(sparkle) ${t}`}}findModelByNeedle(e){let t=(e||"").trim().toLowerCase();if(t)return this.models.find(n=>{let s=(n.id||"").toLowerCase(),i=(n.name||"").toLowerCase();return s===t||i===t||s.includes(t)||i.includes(t)})}async showPicker(){let e=[{label:"$(sparkle) Auto\uFF08\u63A8\u8350\uFF09",description:"Edit \u7528 Claude Sonnet\uFF0CChat \u7528 Qwen",picked:this.autoMode},{label:"",kind:O.QuickPickItemKind.Separator}];for(let n of this.models)e.push({label:n.name||n.id,description:n.provider||"",picked:!this.autoMode&&this.selectedModel===n.id});this.models.length===0&&e.push({label:this.config.get().model,description:"\u9ED8\u8BA4\u6A21\u578B"});let t=await O.window.showQuickPick(e,{title:"\u777F\u9CB8AI: \u9009\u62E9\u6A21\u578B",placeHolder:"\u9009\u62E9 AI \u6A21\u578B"});if(t){if(t.label.includes("Auto"))this.autoMode=!0,this.selectedModel=null;else{this.autoMode=!1;let n=this.models.find(s=>(s.name||s.id)===t.label);this.selectedModel=n?.id||t.label}this.updateLabel()}}dispose(){for(let e of this.disposables)e.dispose()}};var ie=R(require("vscode")),G=R(require("path")),se=class{constructor(e){this.context=e}_cached=null;_cachedAt=0;get(){return this._cached&&Date.now()-this._cachedAt<3e4?this._cached:(this._cached=this._load(),this._cachedAt=Date.now(),this._cached)}invalidate(){this._cached=null}_load(){let e=ie.workspace.getConfiguration("ruijing-ai"),t={},n=ie.workspace.workspaceFolders;if(n?.length)try{let s=G.join(n[0].uri.fsPath,".vscode","ruijing-ai.json"),i=require("fs");i.existsSync(s)&&(t=JSON.parse(i.readFileSync(s,"utf-8")))}catch{}return{workspaceId:t.workspaceId||"",ideToken:t.ideToken||"",apiBase:t.apiBase||e.get("apiBase")||"",harnessApiBase:t.harnessApiBase||this._deriveHarnessApiBase(t.apiBase||e.get("apiBase")||""),apiKey:t.apiKey||e.get("apiKey")||"",model:t.model||e.get("model")||"MiniMax-M2.7",conversationId:this._parseConversationId(t.conversationId),autoMode:e.get("autoMode")??!0}}async updateWorkspaceConfig(e){let t=ie.workspace.workspaceFolders;if(!t?.length)return;let n=require("fs"),s=G.join(t[0].uri.fsPath,".vscode","ruijing-ai.json"),i={};try{n.existsSync(s)&&(i=JSON.parse(n.readFileSync(s,"utf-8")))}catch{i={}}let o={...i,...e};n.mkdirSync(G.dirname(s),{recursive:!0}),n.writeFileSync(s,JSON.stringify(o,null,2),"utf-8"),this.invalidate()}_parseConversationId(e){if(typeof e=="number"&&Number.isFinite(e))return e;if(typeof e=="string"&&e.trim()){let t=Number(e);if(Number.isFinite(t))return t}return null}_deriveHarnessApiBase(e){return(e||"").replace("/api/coding/","/api/harness/coding/")}getEndpoint(e){let t=this.get();return t.workspaceId&&t.apiBase?`${t.apiBase}/workspace/${t.workspaceId}/ide${e}`:t.apiBase?`${t.apiBase}${e}`:e}getHarnessEndpoint(e){let t=this.get(),n=t.harnessApiBase||this._deriveHarnessApiBase(t.apiBase);return t.workspaceId&&n?`${n}/workspace/${t.workspaceId}/ide${e}`:n?`${n}${e}`:e}getHeaders(){let e=this.get(),t={"Content-Type":"application/json"};return e.ideToken?(t["X-Vibe-IDE-Token"]=e.ideToken,t.Authorization=`Bearer ${e.ideToken}`):e.apiKey&&(t.Authorization=`Bearer ${e.apiKey}`),t}};var q=R(require("vscode")),Ve={"df.":`df-sdk v2 API:
  df.requestWithPromise({url, method, params, headers, timeout, disableSuccessMsg, disableErrorMsg}) \u2192 .asyncThen().asyncErrorCatch()
  df.uploadWithPromise({url, params(FormData), headers, timeout})
  df.showToast({message, type, duration})
  df.page.openGlobalModal({title, message, okConfig, cancelConfig})
  df.page.openFormModal({formInfo: {formId, title, documentId, onBtnClickCallback}})
  df.page.openFormDrawer({formInfo: {formId, title, rowDocumentId, onBtnClickCallback}})
  df.page.openFormListModal({formInfo: {formId, title, currentMenu, tabId, filterParam}})
  df.getVue() df.getRouter() df.getStore() df.getEnv() df.getI18n()`,"formEngine.":`FormEngine API:
  formEngine.formDataControl.formValue \u2014 \u8868\u5355\u6570\u636E
  formEngine.formDataControl.updateFormValue(value)
  formEngine.formDataControl.getFormItemByUuid(uuid)
  formEngine.formDataControl.formConfig \u2014 \u8868\u5355\u914D\u7F6E
  formEngine.actionControl.executeActionWithPromise(actionCode, payload)
  formEngine.actionControl.registerAction(actionCode, action)
  formEngine.extendControl.mountedInstance(el, vm, component, Vue)
  formEngine.ruleControl.setComponentValue(compConfig, value)
  formEngine.bsEventControl.triggerFormOperation(buttonConfig)`,"listEngine.":`ListEngine API:
  listEngine.listDataControl.queryLists \u2014 \u5217\u8868\u6570\u636E
  listEngine.listDataControl.selectedFormData \u2014 \u9009\u4E2D\u884C
  listEngine.listDataControl.tableConfig \u2014 \u8868\u683C\u914D\u7F6E
  listEngine.actionControl.executeActionWithPromise(actionCode, payload)
  listEngine.engineContext.instance \u2014 {formId, appId, menuId, tenantId}`,"NetworkControl.":`NetworkControl API (\u9759\u6001\u65B9\u6CD5):
  NetworkControl.globalRequest(config) \u2014 \u5F02\u6B65\u8BF7\u6C42
  NetworkControl.globalSyncRequest(config) \u2014 \u540C\u6B65\u8BF7\u6C42
  NetworkControl.globalUpload(config, onUploadProgress)
  NetworkControl.globalDownload(config, onDownloadProgress)
  NetworkControl.apis \u2014 \u6240\u6709 API \u914D\u7F6E
  NetworkControl.token \u2014 \u5F53\u524D token`},oe=class{constructor(e,t){this.config=e;this.modelSelector=t}lastRequestController=null;debounceTimer=null;async provideInlineCompletionItems(e,t,n,s){let i=e.lineAt(t.line).text;if(!i.trim())return;this.lastRequestController?.abort(),this.lastRequestController=new AbortController;let o=this.lastRequestController;if(await new Promise((x,C)=>{this.debounceTimer&&clearTimeout(this.debounceTimer),this.debounceTimer=setTimeout(()=>x(),300),s.onCancellationRequested(()=>C(new Error("cancelled"))),o.signal.addEventListener("abort",()=>C(new Error("cancelled")))}).catch(()=>{}),s.isCancellationRequested||o.signal.aborted)return;let r=Math.max(0,t.line-60),c=new q.Range(r,0,t.line,t.character),a=e.getText(c),l=Math.min(e.lineCount-1,t.line+20),m=new q.Range(t.line,t.character,l,e.lineAt(l).text.length),f=e.getText(m);if(!a.trim())return;let u=i.substring(0,t.character),h="";for(let[x,C]of Object.entries(Ve))if(u.includes(x)){h=`

aPaaS \u5E73\u53F0 API \u53C2\u8003:
${C}`;break}let S=this.config.get(),E=this.config.getEndpoint("/completions"),T=this.config.getHeaders(),g=JSON.stringify({prefix:a,suffix:f,language:e.languageId,file_path:q.workspace.asRelativePath(e.uri,!1),max_tokens:256,apaas_context:h||void 0});try{let x=setTimeout(()=>o.abort(),800),C=await fetch(E,{method:"POST",headers:T,body:g,signal:o.signal});if(clearTimeout(x),!C.ok||s.isCancellationRequested)return;let M=(await C.json())?.completions;return M?.length?M.filter(A=>A.text?.trim()).map(A=>new q.InlineCompletionItem(A.text,new q.Range(t,t))):void 0}catch{return}}};var v=R(require("vscode")),X=class{constructor(e,t,n){this.config=e;this.llmClient=t;this.modelSelector=n}static providedCodeActionKinds=[v.CodeActionKind.QuickFix];provideCodeActions(e,t,n,s){let i=n.diagnostics.filter(r=>r.severity===v.DiagnosticSeverity.Error);if(i.length===0)return[];let o=[];for(let r of i.slice(0,3)){let c=new v.CodeAction("\u777F\u9CB8AI: \u89E3\u91CA\u6B64\u9519\u8BEF",v.CodeActionKind.QuickFix);c.command={command:"ruijing-ai.explainDiagnostic",title:"\u89E3\u91CA\u9519\u8BEF",arguments:[e,r]},c.diagnostics=[r],o.push(c);let a=new v.CodeAction("\u777F\u9CB8AI: \u4E00\u952E\u4FEE\u590D",v.CodeActionKind.QuickFix);a.command={command:"ruijing-ai.fixDiagnostic",title:"\u4E00\u952E\u4FEE\u590D",arguments:[e,r]},a.diagnostics=[r],a.isPreferred=!0,o.push(a)}return o}registerCommands(e){e.subscriptions.push(v.commands.registerCommand("ruijing-ai.explainDiagnostic",async(t,n)=>{let s=this.buildExplainMessage(t,n);await v.commands.executeCommand("workbench.action.chat.open",{query:`@ruijing ${s}`})}),v.commands.registerCommand("ruijing-ai.fixDiagnostic",async(t,n)=>{await this.applyQuickFix(t,n)}))}buildExplainMessage(e,t){let n=this.extractContext(e,t);return`\u8BF7\u89E3\u91CA\u4EE5\u4E0B\u4EE3\u7801\u9519\u8BEF\u5E76\u7ED9\u51FA\u4FEE\u590D\u5EFA\u8BAE\uFF1A

\u9519\u8BEF\u4FE1\u606F\uFF1A${t.message}
\u6765\u6E90\uFF1A${t.source||"unknown"}
\u6587\u4EF6\uFF1A${v.workspace.asRelativePath(e.uri)}
\u884C\u53F7\uFF1A${t.range.start.line+1}

\u4EE3\u7801\u4E0A\u4E0B\u6587\uFF1A
\`\`\`${e.languageId}
${n}
\`\`\``}async applyQuickFix(e,t){let n=this.extractContext(e,t),s=v.workspace.asRelativePath(e.uri);await v.window.withProgress({location:v.ProgressLocation.Notification,title:"\u777F\u9CB8AI: \u6B63\u5728\u751F\u6210\u4FEE\u590D..."},async()=>{try{let i=this.modelSelector.resolve(!0),o=await this.llmClient.complete({model:i,messages:[{role:"system",content:`\u4F60\u662F\u4E00\u4E2A\u4EE3\u7801\u4FEE\u590D\u52A9\u624B\u3002\u7528\u6237\u4F1A\u7ED9\u4F60\u4E00\u6BB5\u6709\u9519\u8BEF\u7684\u4EE3\u7801\u548C\u9519\u8BEF\u4FE1\u606F\u3002
\u8BF7\u53EA\u8F93\u51FA\u4FEE\u590D\u540E\u7684\u4EE3\u7801\u7247\u6BB5\uFF08\u4E0D\u8981\u89E3\u91CA\uFF0C\u4E0D\u8981 markdown \u6807\u8BB0\uFF0C\u76F4\u63A5\u8F93\u51FA\u4EE3\u7801\uFF09\u3002
\u53EA\u8F93\u51FA\u9700\u8981\u66FF\u6362\u7684\u90A3\u51E0\u884C\uFF0C\u4E0D\u8981\u8F93\u51FA\u6574\u4E2A\u6587\u4EF6\u3002`},{role:"user",content:`\u6587\u4EF6\uFF1A${s}
\u8BED\u8A00\uFF1A${e.languageId}
\u9519\u8BEF\u4FE1\u606F\uFF1A${t.message}
\u6765\u6E90\uFF1A${t.source||"unknown"}

\u9519\u8BEF\u4EE3\u7801\u4E0A\u4E0B\u6587\uFF08\u9519\u8BEF\u5728\u7B2C ${t.range.start.line+1} \u884C\uFF09\uFF1A
${n}

\u8BF7\u8F93\u51FA\u4FEE\u590D\u540E\u7684\u4EE3\u7801\uFF08\u53EA\u8F93\u51FA\u4E0A\u9762\u8FD9\u6BB5\u4EE3\u7801\u7684\u4FEE\u590D\u7248\u672C\uFF09\uFF1A`}],maxTokens:2048});if(!o.trim()){v.window.showWarningMessage("AI \u672A\u8FD4\u56DE\u4FEE\u590D\u4EE3\u7801");return}let r=Math.max(0,t.range.start.line-15),c=Math.min(e.lineCount-1,t.range.end.line+15),a=new v.Range(r,0,c,e.lineAt(c).text.length),l=new v.WorkspaceEdit,m=this.cleanCodeBlock(o);l.replace(e.uri,a,m),await v.workspace.applyEdit(l),setTimeout(async()=>{v.languages.getDiagnostics(e.uri).filter(u=>u.severity===v.DiagnosticSeverity.Error&&u.message===t.message).length===0?v.window.showInformationMessage("\u777F\u9CB8AI: \u9519\u8BEF\u5DF2\u4FEE\u590D"):v.window.showWarningMessage("\u777F\u9CB8AI: \u5DF2\u5E94\u7528\u4FEE\u590D\uFF0C\u4F46\u9519\u8BEF\u53EF\u80FD\u4ECD\u5B58\u5728\u3002\u8BF7\u68C0\u67E5\u4EE3\u7801\u3002")},2e3)}catch(i){v.window.showErrorMessage(`\u777F\u9CB8AI \u4FEE\u590D\u5931\u8D25: ${i.message}`)}})}extractContext(e,t){let n=Math.max(0,t.range.start.line-15),s=Math.min(e.lineCount-1,t.range.end.line+15),i=[];for(let o=n;o<=s;o++){let r=o===t.range.start.line?">>> ":"    ";i.push(`${r}${o+1}: ${e.lineAt(o).text}`)}return i.join(`
`)}cleanCodeBlock(e){let t=e.trim(),n=t.match(/^```[\w]*\n?([\s\S]*?)```$/);return n&&(t=n[1].trim()),t=t.replace(/^(?:>>> |    )\d+: /gm,""),t}};var w=R(require("vscode")),re=class{constructor(e,t){this.llmClient=e;this.modelSelector=t}registerCommands(e){e.subscriptions.push(w.commands.registerCommand("ruijing-ai.generateTest",()=>this.generate()))}async generate(){let e=w.window.activeTextEditor;if(!e){w.window.showWarningMessage("\u8BF7\u5148\u6253\u5F00\u4E00\u4E2A\u6587\u4EF6\u5E76\u9009\u4E2D\u8981\u6D4B\u8BD5\u7684\u4EE3\u7801");return}let t=e.selection,n=e.document.getText(t);if(!n.trim()){w.window.showWarningMessage("\u8BF7\u9009\u4E2D\u8981\u751F\u6210\u6D4B\u8BD5\u7684\u51FD\u6570\u6216\u4EE3\u7801");return}let s=w.workspace.asRelativePath(e.document.uri,!1),i=e.document.languageId,o=await this.detectTestFramework(),c=e.document.getText().split(`
`).filter(a=>/^(import |const .+ = require|from )/.test(a.trim())).join(`
`);await w.window.withProgress({location:w.ProgressLocation.Notification,title:"\u777F\u9CB8AI: \u6B63\u5728\u751F\u6210\u5355\u5143\u6D4B\u8BD5..."},async()=>{try{let a=this.modelSelector.resolve(!0),l=await this.llmClient.complete({model:a,messages:[{role:"system",content:this.buildSystemPrompt(o,i)},{role:"user",content:this.buildUserPrompt(n,s,i,c)}],maxTokens:4096});if(!l.trim()){w.window.showWarningMessage("AI \u672A\u8FD4\u56DE\u6D4B\u8BD5\u4EE3\u7801");return}let m=this.inferTestFilePath(s,i),f=this.cleanCodeBlock(l),u=w.workspace.workspaceFolders;if(!u?.length)return;let h=w.Uri.joinPath(u[0].uri,m),S=new w.WorkspaceEdit;S.createFile(h,{overwrite:!1,ignoreIfExists:!0}),await w.workspace.applyEdit(S);let E=await w.workspace.openTextDocument(h),T=E.getText(),g=new w.WorkspaceEdit;if(T.trim()){let x=E.lineCount-1,C=new w.Position(x,E.lineAt(x).text.length);g.insert(h,C,`

`+f)}else g.insert(h,new w.Position(0,0),f);await w.workspace.applyEdit(g),await w.window.showTextDocument(h),w.window.showInformationMessage(`\u777F\u9CB8AI: \u6D4B\u8BD5\u5DF2\u751F\u6210\u5230 ${m}`)}catch(a){w.window.showErrorMessage(`\u6D4B\u8BD5\u751F\u6210\u5931\u8D25: ${a.message}`)}})}buildSystemPrompt(e,t){return`\u4F60\u662F\u4E00\u4E2A\u4E13\u4E1A\u7684\u5355\u5143\u6D4B\u8BD5\u751F\u6210\u52A9\u624B\uFF0C\u4E13\u6CE8\u4E8E\u5F97\u5E06 aPaaS \u4F4E\u4EE3\u7801\u5E73\u53F0\u5F00\u53D1\u3002
\u6D4B\u8BD5\u6846\u67B6\uFF1A${e}
\u8BED\u8A00\uFF1A${t}

\u8981\u6C42\uFF1A
- \u751F\u6210\u5B8C\u6574\u53EF\u8FD0\u884C\u7684\u6D4B\u8BD5\u6587\u4EF6
- \u8986\u76D6\u6B63\u5E38\u8DEF\u5F84\u548C\u8FB9\u754C\u60C5\u51B5
- \u5BF9\u4E8E aPaaS \u7EC4\u4EF6\uFF0Cmock \u4EE5\u4E0B\u5E38\u7528\u4F9D\u8D56\uFF1A
  - df.requestWithPromise \u2192 jest.fn() \u8FD4\u56DE Promise
  - df.showToast \u2192 jest.fn()
  - FormWidgetMixin \u7684 this.formValue / this.formEngine \u2192 mock \u5BF9\u8C61
  - NetworkControl.globalRequest \u2192 jest.fn()
- \u4F7F\u7528\u4E2D\u6587\u6CE8\u91CA\u8BF4\u660E\u6BCF\u4E2A\u6D4B\u8BD5\u7528\u4F8B\u7684\u610F\u56FE
- \u53EA\u8F93\u51FA\u4EE3\u7801\uFF0C\u4E0D\u8981\u89E3\u91CA`}buildUserPrompt(e,t,n,s){return`\u4E3A\u4EE5\u4E0B\u4EE3\u7801\u751F\u6210\u5355\u5143\u6D4B\u8BD5\uFF1A

\u6587\u4EF6\u8DEF\u5F84\uFF1A${t}
\u8BED\u8A00\uFF1A${n}

import \u8BED\u53E5\uFF1A
${s}

\u8981\u6D4B\u8BD5\u7684\u4EE3\u7801\uFF1A
\`\`\`${n}
${e}
\`\`\``}async detectTestFramework(){if(!w.workspace.workspaceFolders?.length)return"jest";let t=[{pattern:"**/jest.config.*",framework:"jest"},{pattern:"**/vitest.config.*",framework:"vitest"},{pattern:"**/karma.conf.*",framework:"karma + jasmine"},{pattern:"**/pom.xml",framework:"JUnit 5"}];for(let n of t)if((await w.workspace.findFiles(n.pattern,"**/node_modules/**",1)).length>0)return n.framework;try{let n=await w.workspace.findFiles("package.json","**/node_modules/**",1);if(n.length){let s=await w.workspace.fs.readFile(n[0]),i=JSON.parse(Buffer.from(s).toString("utf-8")),o={...i.devDependencies,...i.dependencies};if(o.vitest)return"vitest";if(o.jest)return"jest";if(o.mocha)return"mocha"}}catch{}return"jest"}inferTestFilePath(e,t){let n=t==="java"?".java":e.match(/\.\w+$/)?.[0]||".js",s=e.replace(/\.\w+$/,"");if(t==="java")return s.replace("src/main/","src/test/")+"Test"+n;let i=s.split("/").slice(0,-1).join("/"),o=s.split("/").pop()||"test";return`${i}/__tests__/${o}.test${n===".vue"?".js":n}`}cleanCodeBlock(e){let t=e.trim(),n=t.match(/^```[\w]*\n?([\s\S]*?)```$/);return n&&(t=n[1].trim()),t}};var I=R(require("vscode")),ae=class{constructor(e,t){this.llmClient=e;this.modelSelector=t}registerCommands(e){e.subscriptions.push(I.commands.registerCommand("ruijing-ai.reviewCode",()=>this.review()))}async review(){let e=I.window.activeTextEditor;if(!e){I.window.showWarningMessage("\u8BF7\u5148\u6253\u5F00\u4E00\u4E2A\u6587\u4EF6\u5E76\u9009\u4E2D\u8981\u5BA1\u67E5\u7684\u4EE3\u7801");return}let t=e.selection,n,s;if(t.isEmpty?(s=e.visibleRanges[0]||new I.Range(0,0,e.document.lineCount-1,0),n=e.document.getText(s)):(s=t,n=e.document.getText(t)),!n.trim()){I.window.showWarningMessage("\u6CA1\u6709\u53EF\u5BA1\u67E5\u7684\u4EE3\u7801");return}let i=I.workspace.asRelativePath(e.document.uri,!1),o=e.document.languageId;await I.window.withProgress({location:I.ProgressLocation.Notification,title:"\u777F\u9CB8AI: \u6B63\u5728\u5BA1\u67E5\u4EE3\u7801..."},async()=>{try{let r=this.modelSelector.resolve(!0),c=await this.llmClient.complete({model:r,messages:[{role:"system",content:Ye},{role:"user",content:`\u5BA1\u67E5\u4EE5\u4E0B\u4EE3\u7801\uFF1A

\u6587\u4EF6\uFF1A${i}
\u8BED\u8A00\uFF1A${o}
\u884C\u53F7\u8303\u56F4\uFF1A${s.start.line+1}-${s.end.line+1}

\`\`\`${o}
${n.slice(0,8e3)}
\`\`\``}],maxTokens:4096});if(!c.trim()){I.window.showInformationMessage("\u777F\u9CB8AI: \u4EE3\u7801\u5BA1\u67E5\u672A\u53D1\u73B0\u95EE\u9898");return}await I.commands.executeCommand("workbench.action.chat.open",{query:`@ruijing \u4EE3\u7801\u5BA1\u67E5\u7ED3\u679C\uFF08${i}\uFF09\uFF1A

${c}`})}catch(r){I.window.showErrorMessage(`\u4EE3\u7801\u5BA1\u67E5\u5931\u8D25: ${r.message}`)}})}},Ye=`\u4F60\u662F\u5F97\u5E06 aPaaS \u4F4E\u4EE3\u7801\u5E73\u53F0\u7684\u4EE3\u7801\u5BA1\u67E5\u4E13\u5BB6\u3002\u8BF7\u4ECE\u4E09\u4E2A\u7EF4\u5EA6\u5BA1\u67E5\u4EE3\u7801\uFF1A

## 1. \u901A\u7528\u8D28\u91CF
- \u4EE3\u7801\u590D\u6742\u5EA6\u662F\u5426\u8FC7\u9AD8\uFF08\u5708\u590D\u6742\u5EA6 > 10 \u7684\u51FD\u6570\uFF09
- \u91CD\u590D\u4EE3\u7801
- \u547D\u540D\u662F\u5426\u6E05\u6670
- \u9519\u8BEF\u5904\u7406\u662F\u5426\u5B8C\u5584
- \u6F5C\u5728\u7684 null/undefined \u98CE\u9669

## 2. \u6027\u80FD
- \u4E0D\u5FC5\u8981\u7684\u91CD\u590D\u6E32\u67D3\uFF08Vue computed vs watch \u4F7F\u7528\u4E0D\u5F53\uFF09
- \u5185\u5B58\u6CC4\u6F0F\uFF08\u4E8B\u4EF6\u76D1\u542C\u672A\u6E05\u7406\u3001\u5B9A\u65F6\u5668\u672A\u6E05\u9664\uFF09
- \u5927\u6570\u7EC4\u64CD\u4F5C\uFF08map/filter \u94FE\u8FC7\u957F\uFF09
- \u4E0D\u5FC5\u8981\u7684 API \u8C03\u7528

## 3. aPaaS \u5E73\u53F0\u89C4\u8303
- \u662F\u5426\u4F7F\u7528 df-sdk v2 \u6807\u51C6 API\uFF08df.requestWithPromise \u800C\u975E\u76F4\u63A5 axios\uFF09
- \u662F\u5426\u6B63\u786E\u4F7F\u7528\u7EC4\u4EF6 Mixin\uFF08FormWidgetMixin \u7684 formValue \u53CC\u5411\u7ED1\u5B9A\uFF09
- componentModelField \u914D\u7F6E\u662F\u5426\u5B8C\u6574
- \u56FD\u9645\u5316\u662F\u5426\u4F7F\u7528 df.getI18n().t() \u800C\u975E\u786C\u7F16\u7801\u4E2D\u6587
- \u662F\u5426\u9075\u5FAA\u811A\u624B\u67B6\u76EE\u5F55\u7ED3\u6784\u7EA6\u5B9A

## \u8F93\u51FA\u683C\u5F0F
\u5BF9\u6BCF\u4E2A\u53D1\u73B0\u7684\u95EE\u9898\uFF0C\u8F93\u51FA\uFF1A
- **\u95EE\u9898**\uFF1A\u7B80\u8FF0\u95EE\u9898
- **\u4F4D\u7F6E**\uFF1A\u884C\u53F7\u6216\u4EE3\u7801\u7247\u6BB5
- **\u5EFA\u8BAE**\uFF1A\u4FEE\u590D\u65B9\u6848
- **\u4FEE\u590D\u4EE3\u7801**\uFF1A\u5982\u679C\u80FD\u7ED9\u51FA\u5177\u4F53\u4FEE\u590D\u4EE3\u7801\uFF08\u7528 \`\`\` \u5305\u88F9\uFF09

\u5982\u679C\u4EE3\u7801\u8D28\u91CF\u826F\u597D\uFF0C\u8F93\u51FA"\u4EE3\u7801\u8D28\u91CF\u826F\u597D\uFF0C\u672A\u53D1\u73B0\u660E\u663E\u95EE\u9898"\u3002`;var B=R(require("vscode")),ce=class d{disposables=[];errorBuffer=[];lastNotifyTime=0;static NOTIFY_COOLDOWN=15e3;static ERROR_PATTERNS=[/Error:/i,/ERR!/,/FAILED/i,/BUILD FAILED/i,/SyntaxError/,/TypeError/,/ReferenceError/,/ENOENT/,/EISDIR/,/EACCES/,/npm ERR/i,/FATAL/i,/Exception/,/Traceback/,/at\s+\S+\s+\(\S+:\d+:\d+\)/,/^\s*at\s+/,/command not found/,/Cannot find module/,/Module not found/,/spawn\s+\S*\s+ENOENT/];static APAAS_ERROR_HINTS={EISDIR:"df-apaas-cli build \u8DEF\u5F84\u53EF\u80FD\u542B\u7A7A\u683C\uFF0C\u5EFA\u8BAE\u5C06 workspace \u79FB\u5230\u65E0\u7A7A\u683C\u8DEF\u5F84","spawn UNKNOWN":"\u53EF\u80FD\u662F Chromium \u8DEF\u5F84\u672A\u914D\u7F6E\uFF0C\u9700\u8BBE\u7F6E DF_APAAS_CLI_CHROMIUM_PATH \u73AF\u5883\u53D8\u91CF",ETARGET:"npm \u5305\u7248\u672C\u4E0D\u5339\u914D\uFF0C\u68C0\u67E5 package.json \u4E2D\u7684\u4F9D\u8D56\u7248\u672C","registry.dfy.definesys.cn":"\u79C1\u6709 npm registry \u8FDE\u63A5\u5931\u8D25\uFF0C\u68C0\u67E5\u7F51\u7EDC\u6216 registry \u914D\u7F6E","df-apaas-cli: command not found":"\u9700\u8981\u5B89\u88C5 @x-apaas/df-apaas-cli: npm i -g @x-apaas/df-apaas-cli"};constructor(){try{let e=B.window;if(typeof e.onDidWriteTerminalData=="function"){let t=e.onDidWriteTerminalData(n=>{this.onTerminalData(n.data)});this.disposables.push(t),console.log("[RuijingAI] Terminal data listener active")}else console.log("[RuijingAI] onDidWriteTerminalData not available, terminal error detection limited to exit codes")}catch{console.warn("[RuijingAI] Terminal data listener not available")}this.disposables.push(B.window.onDidCloseTerminal(e=>{e.exitStatus&&e.exitStatus.code!==0&&this.offerAnalysis(`\u8FDB\u7A0B\u9000\u51FA\u7801: ${e.exitStatus.code}`)}))}onTerminalData(e){let t=e.split(/\r?\n/);for(let n of t)n.trim()&&(this.errorBuffer.push(n),this.errorBuffer.length>150&&this.errorBuffer.shift());for(let n of d.ERROR_PATTERNS)if(n.test(e)){this.offerAnalysis(e.slice(0,200));break}}async offerAnalysis(e){let t=Date.now();if(t-this.lastNotifyTime<d.NOTIFY_COOLDOWN)return;this.lastNotifyTime=t;let n="";for(let[r,c]of Object.entries(d.APAAS_ERROR_HINTS))if(e.includes(r)||this.errorBuffer.some(a=>a.includes(r))){n=`

\u63D0\u793A\uFF1A${c}`;break}if(await B.window.showWarningMessage(`\u68C0\u6D4B\u5230\u7EC8\u7AEF\u9519\u8BEF\uFF0C\u662F\u5426\u8BA9 AI \u5206\u6790\uFF1F${n?" (\u5DF2\u8BC6\u522B\u4E3A aPaaS \u76F8\u5173\u9519\u8BEF)":""}`,"\u5206\u6790\u9519\u8BEF","\u5FFD\u7565")!=="\u5206\u6790\u9519\u8BEF")return;let o=`\u8BF7\u5206\u6790\u4EE5\u4E0B\u7EC8\u7AEF\u9519\u8BEF\u8F93\u51FA\u5E76\u7ED9\u51FA\u4FEE\u590D\u5EFA\u8BAE\uFF1A

\`\`\`
${this.errorBuffer.slice(-100).join(`
`).slice(0,4e3)}
\`\`\``;n&&(o+=`

${n}`);try{let r=await B.workspace.findFiles("package.json","**/node_modules/**",1);if(r.length){let c=await B.workspace.fs.readFile(r[0]),a=JSON.parse(Buffer.from(c).toString("utf-8"));o+=`

\u9879\u76EE\u4FE1\u606F\uFF1A
name: ${a.name}
scripts: ${JSON.stringify(a.scripts||{}).slice(0,300)}`}}catch{}await B.commands.executeCommand("workbench.action.chat.open",{query:`@ruijing ${o}`})}dispose(){for(let e of this.disposables)e.dispose()}};var b=R(require("vscode")),le=class{constructor(e,t){this.llmClient=e;this.modelSelector=t}registerCommands(e){e.subscriptions.push(b.commands.registerCommand("ruijing-ai.generateCommitMessage",()=>this.generateCommitMessage()),b.commands.registerCommand("ruijing-ai.explainDiff",()=>this.explainDiff()))}async generateCommitMessage(){let e=b.workspace.workspaceFolders;if(!e?.length){b.window.showWarningMessage("\u8BF7\u5148\u6253\u5F00\u4E00\u4E2A\u5DE5\u4F5C\u533A");return}let t=e[0].uri.fsPath;await b.window.withProgress({location:b.ProgressLocation.Notification,title:"\u777F\u9CB8AI: \u6B63\u5728\u751F\u6210 commit message..."},async()=>{try{let n=await this.runGit(t,["diff","--cached","--stat"]),s=await this.runGit(t,["diff","--cached"]);if(!n.trim()&&!s.trim()&&(n=await this.runGit(t,["diff","--stat"]),!n.trim())){b.window.showWarningMessage("\u6CA1\u6709\u68C0\u6D4B\u5230\u4EE3\u7801\u53D8\u66F4");return}let i=this.modelSelector.resolve(!1),r=(await this.llmClient.complete({model:i,messages:[{role:"system",content:`\u4F60\u662F\u4E00\u4E2A Git commit message \u751F\u6210\u52A9\u624B\u3002\u6839\u636E diff \u751F\u6210\u7B80\u6D01\u7684\u4E2D\u6587 commit message\u3002
\u683C\u5F0F\u8981\u6C42\uFF1Atype(scope): \u63CF\u8FF0
type: feat/fix/refactor/style/docs/test/chore
scope: \u6539\u52A8\u6D89\u53CA\u7684\u6A21\u5757\uFF08\u53EF\u9009\uFF09
\u63CF\u8FF0: \u4E00\u53E5\u8BDD\u8BF4\u660E\u6539\u4E86\u4EC0\u4E48\uFF08\u4E0D\u8D85\u8FC7 50 \u5B57\uFF09

\u53EA\u8F93\u51FA commit message\uFF0C\u4E0D\u8981\u5176\u4ED6\u5185\u5BB9\u3002`},{role:"user",content:`\u6587\u4EF6\u53D8\u66F4\u7EDF\u8BA1\uFF1A
${n.slice(0,1e3)}

\u8BE6\u7EC6 diff\uFF08\u524D 3000 \u5B57\u7B26\uFF09\uFF1A
${s.slice(0,3e3)}`}],maxTokens:200})).trim().replace(/^["']|["']$/g,"");if(!r){b.window.showWarningMessage("AI \u672A\u8FD4\u56DE commit message");return}let c=b.extensions.getExtension("vscode.git");if(c){let a=c.exports?.getAPI?.(1);if(a?.repositories?.length){a.repositories[0].inputBox.value=r,b.window.showInformationMessage("\u777F\u9CB8AI: commit message \u5DF2\u586B\u5165");return}}await b.env.clipboard.writeText(r),b.window.showInformationMessage(`\u777F\u9CB8AI: commit message \u5DF2\u590D\u5236\u5230\u526A\u8D34\u677F: ${r}`)}catch(n){b.window.showErrorMessage(`\u751F\u6210 commit message \u5931\u8D25: ${n.message}`)}})}async explainDiff(){let e=b.workspace.workspaceFolders;if(!e?.length)return;let t=e[0].uri.fsPath;try{let n=await this.runGit(t,["diff","--cached"]);if(n.trim()||(n=await this.runGit(t,["diff"])),!n.trim()){b.window.showWarningMessage("\u6CA1\u6709\u68C0\u6D4B\u5230\u4EE3\u7801\u53D8\u66F4");return}let s=`\u8BF7\u89E3\u91CA\u4EE5\u4E0B\u4EE3\u7801\u53D8\u66F4\u7684\u5185\u5BB9\u548C\u76EE\u7684\uFF1A

\`\`\`diff
${n.slice(0,6e3)}
\`\`\``;await b.commands.executeCommand("workbench.action.chat.open",{query:`@ruijing ${s}`})}catch(n){b.window.showErrorMessage(`\u83B7\u53D6 diff \u5931\u8D25: ${n.message}`)}}runGit(e,t){return new Promise((n,s)=>{require("child_process").execFile("git",t,{cwd:e,maxBuffer:1024*1024},(o,r,c)=>{if(o&&!r){s(new Error(c||o.message));return}n(r||"")})})}};function Qe(d){console.log("[RuijingAI] Extension activating...");let e=new se(d),t=new H(e),n=new ne(e),s=new te(e,n),i=U.chat.createChatParticipant("ruijing-ai.chat",s.handle.bind(s));i.iconPath=U.Uri.joinPath(d.extensionUri,"icon.png"),i.followupProvider=s.getFollowupProvider(),d.subscriptions.push(i,n);let o=new oe(e,n);d.subscriptions.push(U.languages.registerInlineCompletionItemProvider({pattern:"**"},o));let r=new X(e,t,n);d.subscriptions.push(U.languages.registerCodeActionsProvider({pattern:"**"},r,{providedCodeActionKinds:X.providedCodeActionKinds})),r.registerCommands(d),new re(t,n).registerCommands(d),new ae(t,n).registerCommands(d);let l=new ce;d.subscriptions.push(l),new le(t,n).registerCommands(d),n.loadModels(t).catch(f=>{console.warn("[RuijingAI] Failed to load models:",f)}),console.log("[RuijingAI] Extension activated (Phase 1 + Phase 2)")}function Ze(){console.log("[RuijingAI] Extension deactivated")}0&&(module.exports={activate,deactivate});
//# sourceMappingURL=extension.js.map
