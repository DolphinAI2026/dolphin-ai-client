# Huabao remote Code Runtime recovery

```yaml
agentic_debug_loop:
  max_iterations: 3
  success_criteria:
    - "The public Runtime status endpoint for workspace 1787052171860 returns a non-5xx response."
    - "The remote Code session for application dianzi-dan can complete Runtime bootstrap."
  allowed_actions:
    - "kubernetes.rollout_restart"
    - "kubernetes.apply"
  allowed_resources:
    - "dolphin-code namespace Runtime workload, Service, Endpoints, and Ingress for workspace 1787052171860"
```

Scope: diagnose and restore only the remote Code Runtime chain for the affected
Huabao test workspace. Begin with read-only Kubernetes evidence. Any change must
target the identified Runtime workload or its routing object, and the public
status endpoint must be checked afterwards.
