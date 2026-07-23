# Task 1: MXC 编译与原生探针门禁

## 改动文件

- `src-tauri/Cargo.toml`
- `src-tauri/Cargo.lock`
- `rust-toolchain.toml`
- `src-tauri/src/lib.rs`
- `src-tauri/src/local_runtime/mod.rs`
- `src-tauri/src/local_runtime/mxc_driver.rs`

## 实现摘要

- 将 crate 的最低 Rust 版本固定为 `1.93`，并新增 `rust-toolchain.toml` 固定
  Rust 1.93、Clippy 和 rustfmt。
- 锁定 `mxc-sdk` 到
  `fd7e9061fabb5188955b79e8a26bd5e476e4d613`，并更新 `Cargo.lock`。
- 新增 `local_runtime::mxc_driver::probe()`。它唯一通过
  `mxc_sdk::platform_support()` 判断宿主支持情况，不自行检查命令是否存在。
- 仅当 MXC 报告 Linux 的 `bubblewrap` 后端可用时返回 `ProbeResult`；
  非 Linux 返回 `UnsupportedPlatform`，MXC probe 不支持或未报告
  Bubblewrap 返回带清晰消息的 `ProbeFailed`，不会降级为无沙箱运行。
- `src-tauri/src/lib.rs` 仅新增 `mod local_runtime;`，未改动既有 sidecar 行为。

## 测试与命令

| 命令 | 结果 |
| --- | --- |
| `rustc --test src-tauri/src/local_runtime/mxc_driver.rs ...`（实现前） | 失败，缺少 `probe` 与 `LocalRuntimeErrorCode`，形成 RED 证据。 |
| `rustup toolchain install 1.93 --component clippy --component rustfmt` | 成功，安装 Rust 1.93.1。 |
| `rustc --version` | 成功，`rustc 1.93.1`。 |
| `cargo fetch --manifest-path src-tauri/Cargo.toml` | 成功，锁定 MXC revision 并更新锁文件。 |
| `cargo metadata --manifest-path src-tauri/Cargo.toml --format-version 1 --no-deps` | 成功。 |
| `cargo check --manifest-path <mxc-sdk>/Cargo.toml --package mxc-sdk` | 成功，固定 revision 的 `mxc-sdk 0.7.0` 在 Rust 1.93.1 下完成编译检查。 |
| `rustc --test src-tauri/src/local_runtime/mxc_driver.rs ... && /tmp/task-1-mxc-driver-test --exact tests::linux_probe_reports_bubblewrap_or_a_blocking_reason` | 成功，1 个测试通过；该测试链接真实 `mxc_sdk::platform_support()`。 |
| `rustfmt --edition 2021 --check src-tauri/src/local_runtime/mod.rs src-tauri/src/local_runtime/mxc_driver.rs` | 成功。 |
| `git diff --check` | 成功。 |
| `podman exec orcamatrix-tauri-ci sh -lc 'export PATH=/root/.cargo/bin:$PATH; rustc --version; cargo test --manifest-path src-tauri/Cargo.toml local_runtime::mxc_driver::tests::linux_probe_reports_bubblewrap_or_a_blocking_reason'` | 成功，持久验证容器中的完整 app crate 测试编译和目标测试均完成；Rust 1.93.1，1 个测试通过、0 个失败，输出无 warning。 |

## 审查修复

- 将 `src-tauri/src/lib.rs` 中的 `local_runtime` 声明调整为 `pub mod local_runtime;`，让
  Task 1 已定义的 `local_runtime::mxc_driver::probe()` 公共接口保持明确可见；未加入假调用、
  crate 级 `allow` 或 Task 4 逻辑。
- `orcamatrix-tauri-ci` 是当前的持久 app crate 验证容器；其中的
  `src-tauri/binaries/ruijing-sidecar-x86_64-unknown-linux-gnu` 仅为 gitignored 的编译期
  sidecar 验收占位，不属于 Task 1 产物，也不再构成当前未解决的系统依赖阻塞。

## 提交

- 实现提交：`fa9d598d517d97cc50b5e2fcc22d22e0f8361fe6`
- 提交信息：`feat: add local MXC runtime probe`
- `mxc_version` 当前反映锁定的 `mxc-sdk 0.7.0`；后续升级 MXC revision 时应同步更新
  该值及对应测试/兼容性验证。
