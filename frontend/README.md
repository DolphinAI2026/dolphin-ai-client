# Frontend

## Stack

- Vue 3
- TypeScript
- Vite
- Element Plus
- Less

## Styling

- 现有页面里的 `.css` 可以继续保留，不要求一次性迁移。
- 新增前端组件统一使用 `<style lang="less">` 或独立 `.less` 文件。
- Vite 已经注入共享 Less 变量文件 `src/styles/tokens.less`，新组件可直接使用其中的变量和 mixin。
