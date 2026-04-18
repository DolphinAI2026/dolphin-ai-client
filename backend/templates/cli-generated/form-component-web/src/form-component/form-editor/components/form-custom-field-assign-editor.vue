<template>
    <form-custom-sechma-item
        class="form-custom-field-assign-editor"
        :label="label"
        :property="property"
        :config-property="configProperty"
        :showRequired="showRequired"
        :help="help"
        :rules="rules"
    >
        <div class="add-assignment" @click="showAssignmentModal">{{$t('formConfig.lovDataSelector.addAssignRelation')}}</div>
        <ul v-show="assignments && assignments.length" class="assignment-list">
            <li
                v-for="(assgin, index) in assignments"
                :key="assgin.target.uuid"
                class="assignment-item"
            >
                <x-ellipsis
                    :label="assgin.origin.label"
                    mode="origin"
                    class="other-form-component comp-span"
                ></x-ellipsis>
                <div class="assign-to-text">{{$t('formConfig.lovDataSelector.assignTo')}}</div>
                <x-ellipsis
                    :label="assgin.target.label"
                    mode="origin"
                    class="other-form-component comp-span"
                ></x-ellipsis>
                <div class="icon-list">
                    <x-svg-icon
                        name="x-lib-delete"
                        class="pointer delete"
                        @click.native="deleteAssignmentItem(index)"
                    ></x-svg-icon>
                </div>
            </li>
        </ul>
        <x-modal
            title="字段数据赋值"
            :append-to-body="true"
            :destroy-on-close="true"
            :okConfig="assignmentFormModal.okConfig"
            :cancelConfig="assignmentFormModal.cancelConfig"
            :modalVisible.sync="assignmentFormModal.modalVisible"
            :modal="false"
            :customModalBg="true"
            width="small"
        >
            <el-form
                ref="formRef"
                :model="assignment"
                class="assignment-add-in-modal form-custom-field-assign-modal"
                @submit.native.prevent
            >
                <el-form-item
                    prop="origin"
                    :label="''"
                    :rules="modalRules['origin']"
                >
                    <el-select
                        v-model="assignment.origin"
                        value-key="uuid"
                        :placeholder="$t('formConfig.lovDataSelector.otherField')"
                        @change="originChange"
                    >
                        <el-option
                            v-for="item in otherFields"
                            :key="item.uuid"
                            :label="item.label"
                            :value="item"
                        >
                        </el-option>
                    </el-select>
                </el-form-item>
                <span class="split">赋值给</span>
                <el-form-item
                    prop="target"
                    :label="''"
                    :rules="modalRules['target']"
                >
                    <el-select
                        v-model="assignment.target"
                        value-key="uuid"
                        :placeholder="$t('formConfig.lovDataSelector.thisField')"
                        :disabled="!assignment.origin"
                    >
                        <el-option
                            v-for="item in showTargetComponentList"
                            :key="item.uuid"
                            :label="item.label"
                            :value="item"
                        >
                        </el-option>
                    </el-select>
                </el-form-item>
            </el-form>
        </x-modal>
    </form-custom-sechma-item>
</template>
<script>
    import EditorFormConfigMixin from '@/mixin/form-config.mixin'
    import FormEditorMixin from '@/mixin/form-editor.mixin'
    import FormCustomSechmaItem from './form-custom-sechma-item.vue'
    import { getAllFormItemListExcludeTable } from '../utils/form-item.util'
    import { EXCLUDE_SHOW_FIELD_TYPE } from '../constant/form-component-types'

    export default {
        name: 'FormCustomFieldAssignEditor',
        mixins: [EditorFormConfigMixin, FormEditorMixin],
        components: {
            FormCustomSechmaItem
        },
        data(){
            return {
                assignment: {
                    origin: null,
                    target: null
                },
                assignmentFormModal: {
                    okConfig: {
                        title: this.$t('common.confirm'),
                        onOk: () => {
                            const {origin, target} = this.assignment;
                            if(!origin || !target){
                                // 触发表单校验且不关闭弹窗
                                this.$refs.formRef.validate();
                                return true;
                            }

                            this.assignments = [...this.assignments, this.assignment]
                        }
                    },
                    cancelConfig: {
                        title: this.$t('common.cancel'),
                        onCancel: () => {}
                    },
                    modalVisible: false
                },
                modalRules: {
                    origin: [
                        this._validate(
                            'required',
                            `他表字段`
                        )
                    ],
                    target: [
                        this._validate(
                            'required',
                            `本表字段`
                        )
                    ]
                },
                allComponentList: [],
                allTargetComponentList: [],
                showTargetComponentList: []
            }
        },
        computed: {
            assignments: {
                get(){
                    const {property} = this;
                    return this.componentConfig.customComponentConfig[property];
                },
                set(assign){
                    const {property} = this;
                    this.componentConfig.customComponentConfig[property] = [...assign];
                }
            }
        },
        props: {
            otherFields: {
                type: Array,
                default: () => ([])
            }
        },
        created(){
            let allComponentList = getAllFormItemListExcludeTable(this.formItemList);
            this.allComponentList = allComponentList;

            const {isInTable, tableUuid, uuid} = this.componentConfig;
            const EXCLUDE_COMPONENT_TYPE = [...EXCLUDE_SHOW_FIELD_TYPE, 'FORM_WIDGET_LOCATION']

            let componentList = allComponentList;

            if(isInTable){
                // 在子表中
                const children = allComponentList.find(component => component.uuid === tableUuid)?.children;
                if(children && children.length){
                    componentList = children;
                }else{
                    componentList = [];
                }
            }

            this.allTargetComponentList = componentList.filter(item => !EXCLUDE_COMPONENT_TYPE.includes(item.componentType) && item.uuid !== uuid);
        },
        methods: {
            showAssignmentModal(){
                this.assignment = {
                    origin: null,
                    target: null
                }
                this.$nextTick(() => {
                    this.$refs.formRef.clearValidate()
                })
                this.assignmentFormModal.modalVisible = true
            },
            deleteAssignmentItem(index) {
                if (this.$modalOptEvent) {
                    this.$modalOptEvent.showGlobalModal({
                        visible: true,
                        title: '删除赋值关系',
                        message: '是否确定删除该赋值关系？',
                        okConfig: {
                            title: this.$t('common.confirm'),
                            onOk: () => {
                                this.assignments.splice(index, 1);
                                this.assignments = [...this.assignments];
                            }
                        },
                        cancelConfig: {
                            title: this.$t('common.cancel')
                        }
                    })
                }
            },
            originChange(component){
                const {assignments, allTargetComponentList} = this;
                const COMPONENTTYPE = [component.componentType, 'FORM_TEXT_INPUT', 'FORM_TEXTAREA_INPUT'];
                const targetUuidList = assignments.map(item => item.target.uuid);

                const components = allTargetComponentList.filter(item => COMPONENTTYPE.includes(item.componentType) && !targetUuidList.includes(item.uuid))
                this.showTargetComponentList = components;
            }
        }
    }
</script>

<style lang="scss">
.assignment-add-in-modal {
    &.form-custom-field-assign-modal {
        .split {
            margin: 0 8px;
            font-size: var(--base-font-size);
        }
    }
}

.form-custom-field-assign-editor{
    &.form-config-item {
        margin-bottom: 24px !important;
    }

    .icon-list{
        display: flex;
        justify-content: flex-end;
        position: absolute;
        right: 0;

        .edit-assignment{
            margin-right: 5px;
        }
    }

    font-size: 12px;
    margin-bottom: 0px !important;
    
    .add-assignment {
        border: dashed 1px #dcdfe6;
        width: 100%;
        height: 32px;
        line-height: 32px;
        font-size: 12px;
        display: inline-block;
        position: relative;
        text-align: center;
        color: #303133;
        cursor: pointer;

        &:hover {
            border-color: #027aff;
            color: #027aff;
        }
    }

    .assignment-list {
        padding: 0;

        .assignment-item {
            outline: none;
            list-style: none;
            line-height: 32px;
            height: 32px;
            width: 100%;
            position: relative;
            margin: 4px 0;

            .comp-span {
                background: #f5f7fa;
                padding: 0 4px;
                color: #303133;
                border-radius: 2px;
                margin: 0 4px;
                font-size: 12px;
            }
        }
    }

    .assignment-list {
        padding: 0;
        display: inline-block;
        width: 100%;

        .assignment-item {
            outline: none;
            list-style: none;
            line-height: 32px;
            height: 32px;
            width: 100%;
            position: relative;
            margin: 4px 0;
            // display: flex;
            // align-items: center;
            display: grid;
            grid-template-columns: 2fr 1fr 2fr 1fr;

            .comp-span {
                background: #f5f7fa;
                padding: 0 4px;
                color: #303133;
                border-radius: 2px;
                margin: 0 4px;
                font-size: 12px;
                // max-width: calc(50% - 46px);
                max-width: none !important;
                text-align: center;
                height: 24px;
                line-height: 24px;
                border-radius: 2px;
            }

            .assign-to-text {
                line-height: 24px;
                text-align: center;
                font-size: var(--base-font-size);
            }
        }
    }
}

</style>
