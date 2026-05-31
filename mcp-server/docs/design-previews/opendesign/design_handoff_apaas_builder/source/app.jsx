// App shell — wires theme, routing, and Cmd+K palette.

const ROUTES = {
  '/':            { crumb: ['aPaaS Builder', '新建'],          page: 'Landing'      },
  '/projects':    { crumb: ['aPaaS Builder', '项目'],          page: 'Projects'     },
  '/apps':        { crumb: ['aPaaS Builder', '应用'],          page: 'Apps'         },
  '/agents':      { crumb: ['aPaaS Builder', '智能体配置'],    page: 'Agents'       },
  '/projects/:id': { crumb: ['aPaaS Builder', '项目', '项目详情'], page: 'ProjectDetail' },
  '/chat':        { crumb: ['aPaaS Builder', '睿鲸 AI Builder'], page: 'ChatPage'   },
  '/specs':       { crumb: ['aPaaS Builder', '设计文档'],      page: 'Specs'        },
  '/industry':    { crumb: ['aPaaS Builder', '行业知识库'],    page: 'Industry'     },
  '/templates':   { crumb: ['aPaaS Builder', '设计文档'],      page: 'Specs'        },
  '/coding':      { crumb: ['aPaaS Builder', '睿鲸 AI Coding'], page: 'CodingPage'  },
  '/vibe':        { crumb: ['aPaaS Builder', 'Vibe Coding'],    page: 'VibePage'    },
  '/marketplace': { crumb: ['aPaaS Builder', '组件市场'],  page: 'Marketplace'  },
  '/mcp':         { crumb: ['aPaaS Builder', 'MCP 管理'],  page: 'MCP'          },
  '/runtime':     { crumb: ['aPaaS Builder', '运行与发布'], page: 'Runtime'      },
  '/admin':       { crumb: ['aPaaS Builder', '平台管理'],  page: 'Admin'        },
  '/login':       { crumb: ['登录'],                       page: 'Login'        },
};

function getRoute() {
  const hash = window.location.hash.replace(/^#/, '');
  const path = (hash.split('?')[0] || '/');
  if (path.startsWith('/projects/')) return '/projects/:id';
  return ROUTES[path] ? path : '/';
}

function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem('aPaaS:theme') || 'light');
  const [route, setRoute] = useState(getRoute);
  const [collapsed, setCollapsed] = useState(false);
  const [cmdkOpen, setCmdkOpen] = useState(false);
  const [role, setRole] = useState(() => localStorage.getItem('aPaaS:role') || 'consultant');
  const [onboardingOpen, setOnboardingOpen] = useState(() => localStorage.getItem('aPaaS:seenOnboarding') !== '1');
  const [deployOpen, setDeployOpen] = useState(false);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('aPaaS:theme', theme);
  }, [theme]);

  useEffect(() => { localStorage.setItem('aPaaS:role', role); }, [role]);

  const closeOnboarding = () => {
    setOnboardingOpen(false);
    localStorage.setItem('aPaaS:seenOnboarding', '1');
  };

  // Listen for hash changes (back/forward)
  useEffect(() => {
    const handler = () => setRoute(getRoute());
    window.addEventListener('hashchange', handler);
    return () => window.removeEventListener('hashchange', handler);
  }, []);

  const navigate = useCallback((path) => {
    const [pathOnly] = path.split('?');
    if (ROUTES[pathOnly] || path.startsWith('/chat')) {
      window.location.hash = '#' + path;
      setRoute(pathOnly);
    }
  }, []);

  // Cmd+K hotkey
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setCmdkOpen(o => !o);
      }
      if (e.key === '/' && !cmdkOpen) {
        const tag = (document.activeElement?.tagName || '').toLowerCase();
        if (tag !== 'input' && tag !== 'textarea') {
          e.preventDefault();
          setCmdkOpen(true);
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [cmdkOpen]);

  const cfg = ROUTES[route] || ROUTES['/'];
  const PageComp = window[cfg.page];

  const themeValue = useMemo(() => ({ theme, setTheme }), [theme]);
  const routeValue = useMemo(() => ({ route, navigate }), [route, navigate]);
  const roleValue = useMemo(() => ({ role, setRole, openDeploy: () => setDeployOpen(true) }), [role]);

  // Login is a special standalone screen — no shell.
  if (route === '/login') {
    return (
      <ThemeCtx.Provider value={themeValue}>
        <RouteCtx.Provider value={routeValue}>
          <RoleCtx.Provider value={roleValue}>
            <PageComp />
          </RoleCtx.Provider>
        </RouteCtx.Provider>
      </ThemeCtx.Provider>
    );
  }

  return (
    <ThemeCtx.Provider value={themeValue}>
      <RouteCtx.Provider value={routeValue}>
        <RoleCtx.Provider value={roleValue}>
          <div className={`app ${collapsed ? 'collapsed' : ''}`} data-screen-label={cfg.crumb.join(' / ')}>
            <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(c => !c)} />
            <div className="workbench">
              <TopBar
                crumb={cfg.crumb}
                actions={null}
                onCmdK={() => setCmdkOpen(true)}
              />
              {PageComp ? <PageComp /> : <div className="page"><div className="page-pad">页面未找到</div></div>}
            </div>
            <CmdK open={cmdkOpen} onClose={() => setCmdkOpen(false)} />
            <DeployModal open={deployOpen} onClose={() => setDeployOpen(false)} />
            <Onboarding open={onboardingOpen} onClose={closeOnboarding} />
          </div>
        </RoleCtx.Provider>
      </RouteCtx.Provider>
    </ThemeCtx.Provider>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <div className="stage">
    <div className="stage-inner" id="stage-inner">
      <App />
    </div>
  </div>
);

// Scale the inner stage to fit the viewport while preserving aspect ratio
function fitStage() {
  const inner = document.getElementById('stage-inner');
  if (!inner) return;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const scale = Math.min(vw / 1440, vh / 900, 1);
  inner.style.transform = `translate(${(vw - 1440 * scale) / 2}px, ${(vh - 900 * scale) / 2}px) scale(${scale})`;
}
window.addEventListener('resize', fitStage);
setTimeout(fitStage, 0);
setTimeout(fitStage, 100);
setTimeout(fitStage, 500);
