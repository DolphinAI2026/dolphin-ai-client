"""aPaaS 平台原子操作层（operations）——将来 generator_v2 / step_executor /
incremental_executor 三条路径共享的原子操作（create_role / create_dict /
create_model / create_form / create_permission 等）会收敛到这里。

当前状态：仅托管已在两条以上路径间共享的 id / 字段工具。真正的原子
"create_*" 操作合并属架构级设计（见仓库根目录 TODO），不在这一批完成。
"""
