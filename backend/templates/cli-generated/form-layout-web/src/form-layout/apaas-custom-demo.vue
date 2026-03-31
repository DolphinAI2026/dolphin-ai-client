<template>
    <x-app-layout :layoutEngine="layoutEngine" :isCollapse="isCollapse">
        <template v-slot:header>
            <x-app-header
                v-if="appInfo"
                :layoutEngine="layoutEngine"
                :appInfo="appInfo"
                :headerComponents="[
                    'XOrgLogo',
                    'XAppLogo',
                    'xLayoutAccountControl',
                ]"
            ></x-app-header>
        </template>
        <template v-slot:menu>
            <x-app-menu
                v-if="menuConfig"
                :menuConfig="menuConfig"
                :showMenu="showMenu && !!appInfo"
                :isCollapse="isCollapse"
                :layoutEngine="layoutEngine"
                @menu-add-click="menuAddClick"
                @change-collapse="changeCollapse"
            ></x-app-menu>
            <div v-if="!!pkgVersion" class="platform-version">
                <span>
                    {{ pkgVersion }}
                </span>
            </div>
        </template>
        <template slot="appPage" v-if="copyrightPosition">
            <div class="app-custom-wrapper">
                <slot name="appPage"></slot>
            </div>
            <div class="copy-right">
                <span class="copy">CopyRight©️&nbsp;</span>
                <span class="company">{{ copyright }}</span>
            </div>
        </template>
        <template slot="appPage" v-else>
            <div class="app-custom-wrapper">
                <slot name="appPage"></slot>
                <div class="copy-right-manager">
                    <span class="copy">CopyRight©️&nbsp;</span>
                    <span class="company">{{ copyright }}</span>
                </div>
            </div>
        </template>
    </x-app-layout>
</template>
<script>
export default {
    name: "CustomLayout",
    props: {
        layoutEngine: {
            type: Object,
            default: function () {
                return {};
            },
        },
        pkgVersion: {
            type: String,
            default: "",
        },
    },
    data() {
        return {
            isCollapse: false,
            showMenu: true,
            copyright: "上海得帆信息技术有限公司版权所有",
        };
    },
    computed: {
        appInfo() {
            return (
                (this.layoutEngine &&
                    this.layoutEngine.layoutDataControl &&
                    this.layoutEngine.layoutDataControl.appInfo) ||
                {}
            );
        },
        menuConfig() {
            return (
                (this.layoutEngine &&
                    this.layoutEngine.layoutDataControl &&
                    this.layoutEngine.layoutDataControl.menuConfig) || {
                    menu: [],
                    defaultActive: null,
                    menuTreeData: [],
                }
            );
        },
        copyrightPosition() {
            const { name } = this.$route;
            return ![
                "todo-manage-page",
                "toread-page",
                "todo-page",
                "mysubmit-page",
                "todoed-page",
                "process-authorize-page",
                "process-forward-page",
            ].includes(name);
        },
    },
    methods: {
        changeCollapse() {
            this.showMenu = false;
            this.$nextTick(() => {
                this.isCollapse = !this.isCollapse;
                this.showMenu = true;
            });
        },
        menuAddClick(e) {
            this.$emit("menu-add-click", e);
        },
    },
};
</script>
<style lang="scss">
$--app-box-bgColor: #ffffff;
$--app-box-border-color: #dcdfe6;

.x-app-layout {
    .layout-header {
        .x-app-header {
            height: 60px !important;
            // box-shadow: 0 0 0 0 #fff !important;

            .message-center {
                .msg-drawer {
                    color: var(--base-font-color);
                }
            }
        }
    }
    .x-layout-account-control {
        .message-center {
            .el-drawer__wrapper {
                margin-top: 60px !important;
            }
            .v-modal {
                top: 60px !important;
            }
        }
    }
    .layout-middle {
        .layout-center {
            color: var(--base-font-color);
            .menu-switch {
                width: 14px;
                height: 80px;
                padding-right: 2px;
                border-top-right-radius: 18px;
                border-bottom-right-radius: 18px;
                border: 1px solid $--app-box-bgColor;
                border-left: 0;
                background-color: $--app-box-bgColor;
                position: absolute;
                top: calc(50vh - 87px);
                left: -20px;
                transform: translateX(120%);
                cursor: pointer;
                opacity: 0.5;
                display: flex;
                justify-content: center;
                align-items: center;
                z-index: 500;
                border: 1px solid $--app-box-border-color;
                border-left: none;
            }
            .menu-switch:hover {
                background-color: $--app-box-bgColor;
                opacity: 1;
                box-shadow: 2px 0px 4px 0px $--app-box-border-color;
            }
        }
    }

    .app-custom-wrapper {
        width: 100%;
        height: calc(100% - 40px);
        position: relative;
        overflow-y: auto;
        //   padding-top: 24px;
        //   padding-left: 24px;
        //   padding-right: 24px;
        //   padding-bottom: 40px;
        background: #f8f9fa;
        box-sizing: border-box;
        box-shadow: 0px 2px 4px 0px rgba(0, 0, 0, 0.13);
        .app-engine-page {
            background: #ffffff;
            box-shadow: 0px 1px 8px 0px rgba(0, 0, 0, 0.1);
        }
    }
    .copy-right {
        height: 40px;
        text-align: center;
        position: absolute;
        left: 50%;
        bottom: 0;
        transform: translateX(-50%);
        span {
            font-family: PingFangSC-Regular;
            font-size: 12px;
            color: #999999;
            line-height: 40px;
            font-weight: 400;
        }
    }
    .copy-right-manager {
        height: 40px;
        text-align: center;
        position: fixed;
        left: 50%;
        bottom: 0;
        transform: translateX(-50%);
        span {
            font-family: PingFangSC-Regular;
            font-size: 12px;
            color: #999999;
            line-height: 40px;
            font-weight: 400;
        }
    }
}
</style>
