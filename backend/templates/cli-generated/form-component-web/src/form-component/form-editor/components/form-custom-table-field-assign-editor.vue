<!--
 * @Author: 可以清心
 * @Description: 
 * @Date: 2023-01-17 10:44:20
 * @LastEditTime: 2026-04-17 11:04:14
-->
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
        <div class="add-assignment" @click="showTableAssignmentModal">添加子表格赋值</div>
        <ul v-show="assignments && assignments.length" class="parent-assign-list">
            <li
                v-for="assign in assignments"
                :key="assign.target.uuid"
                class="parent-assign-item"
            >
                <ul v-show="assign.assignmentList && assign.assignmentList.length" class="assignment-list">
                    <li
                        v-for="(item, index) in assign.assignmentList"
                        :key="item.target.uuid"
                        class="assignment-item"
                    >
                        <x-ellipsis
                            :label="item.origin.label"
                            mode="origin"
                            class="other-form-component comp-span"
                        ></x-ellipsis>
                        <div class="assign-to-text">{{$t('formConfig.lovDataSelector.assignTo')}}</div>
                        <x-ellipsis
                            :label="item.target.label"
                            mode="origin"
                            class="other-form-component comp-span"
                        ></x-ellipsis>
                        <div class="icon-list">
                            <x-svg-icon
                                name="x-lib-delete"
                                class="pointer delete"
                                @click.native="deleteTableAssignmentItem(assign, index)"
                            ></x-svg-icon>
                        </div>
                    </li>
                </ul>
                <div class="add-table-assign" @click="addTableAssign(assign)">
                    <x-svg-icon name="add-circle-icon"></x-svg-icon>
                    <span>添加赋值规则</span>
                </div>
                <div class="delete-table-assign" @click="deleteTableAssign(assign)">
                    <x-svg-icon name="x-lib-delete"></x-svg-icon>
                    <span>删除子表格赋值</span>
                </div>
            </li>
        </ul>
        
        <x-modal
            title="子表格赋值"
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
                        :key="originFieldsKey"
                        v-model="assignment.origin"
                        value-key="uuid"
                        :placeholder="$t('formConfig.lovDataSelector.otherField')"
                        @change="originChange"
                    >
                        <el-option
                            v-for="item in originFields"
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

        <x-modal
            title="子表赋值规则"
            :append-to-body="true"
            :destroy-on-close="true"
            :okConfig="tableAssignmentFormModal.okConfig"
            :cancelConfig="tableAssignmentFormModal.cancelConfig"
            :modalVisible.sync="tableAssignmentFormModal.modalVisible"
            :modal="false"
            :customModalBg="true"
            width="600"
        >
            <el-form
                ref="tableFormRef"
                :model="tableAssignment"
                class="assignment-add-in-modal form-custom-field-assign-modal"
                @submit.native.prevent
            >
                <el-form-item
                    style="margin-right: 1rem;"
                    prop="target"
                    :label="''"
                    :rules="tableAssignmentRules['target']"
                >
                    <el-select
                        v-model="tableAssignment.target"
                        value-key="uuid"
                        placeholder="目标子表格"
                    >
                        <el-option
                            v-for="item in tableFields"
                            :key="item.uuid"
                            :label="item.label"
                            :value="item"
                        >
                        </el-option>
                    </el-select>
                </el-form-item>
                <el-form-item
                    style="margin-right: 1rem;"
                    prop="origin"
                    :label="''"
                    :rules="modalRules['origin']"
                >
                    <el-select
                        v-model="tableAssignment.origin"
                        value-key="uuid"
                        placeholder="数据来源子表格"
                    >
                        <el-option
                            v-for="item in otherTableFields"
                            :key="item.uuid"
                            :label="item.label"
                            :value="item"
                        >
                        </el-option>
                    </el-select>
                </el-form-item>
                <el-form-item
                    prop="type"
                    :label="''"
                    :rules="modalRules['type']"
                >
                    <el-select
                        v-model="tableAssignment.type"
                        placeholder="子表赋值规则"
                    >
                        <el-option
                            v-for="item in typeOptions"
                            :key="item.value"
                            :label="item.label"
                            :value="item.value"
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
    import { getAllSonTableFormItemList } from '../utils/form-item.util'

    export default {
        name: 'FormCustomTableFieldAssignEditor',
        mixins: [EditorFormConfigMixin, FormEditorMixin],
        components: {
            FormCustomSechmaItem
        },
        data(){
            return {
                tableAssignment: {
                    origin: null,
                    target: null,
                    type: "",
                    assignmentList: []
                },
                tableAssignmentFormModal: {
                    okConfig: {
                        title: this.$t('common.confirm'),
                        onOk: () => {
                            const {origin, target, type} = this.tableAssignment;
                            if(!origin || !target || !type){
                                // 触发表单校验且不关闭弹窗
                                this.$refs.tableFormRef.validate();
                                return true;
                            }

                            this.assignments = [...this.assignments, this.tableAssignment]
                        }
                    },
                    cancelConfig: {
                        title: this.$t('common.cancel'),
                        onCancel: () => {}
                    },
                    modalVisible: false
                },
                tableAssignmentRules: {
                    origin: [
                        this._validate(
                            'required',
                            `来源子表格`
                        )
                    ],
                    target: [
                        this._validate(
                            'required',
                            `目标子表格`
                        )
                    ],
                    type: [
                        this._validate(
                            'required',
                            `子表赋值规则`
                        )
                    ]
                },
                currentTableAssign: null,
                originFieldsKey: 1,
                assignmentFormModal: {
                    okConfig: {
                        title: this.$t('common.confirm'),
                        onOk: () => {
                            const { currentTableAssign } = this;
                            const {origin, target} = this.assignment;
                            if(!origin || !target){
                                // 触发表单校验且不关闭弹窗
                                this.$refs.formRef.validate();
                                return true;
                            }

                            const assign = this.assignments.find(item => item.target.uuid === currentTableAssign.target.uuid);

                            if (assign) {
                                assign.assignmentList = [...assign.assignmentList, this.assignment];
                            }
                            // this.assignments = [...this.assignments, this.assignment]
                        }
                    },
                    cancelConfig: {
                        title: this.$t('common.cancel'),
                        onCancel: () => {}
                    },
                    modalVisible: false
                },
                assignment: {
                    origin: null,
                    target: null
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
            },
            tableFields() {
                const uuidList = this.assignments.map(item => item.target.uuid);

                let tableList = getAllSonTableFormItemList(this.formItemList);
                return tableList.filter(item => !uuidList.includes(item.uuid));
            },
            typeOptions() {
                return [
                    {
                        value: "all",
                        label: "全量赋值"
                    },
                    {
                        value: "add",
                        label: "增量赋值"
                    }
                ]
            },
            originFields() {
                // eslint-disable-next-line
                let { currentTableAssign, getComponentType, otherTableFields } = this;

                if (currentTableAssign) {
                    let field = otherTableFields.find(field => field.uuid === currentTableAssign.origin.uuid);

                    if (field) {
                        let children = field.children;

                        if (children && children.length) {
                            return children.map(item => ({
                                uuid: item.name,
                                label: item.label,
                                // componentType: getComponentType(item.realyType),
                                componentType: item.componentType,
                                oj: item,
                            }))
                        }
                    }
                }

                return [];
            }
        },
        props: {
            otherTableFields: {
                type: Array,
                default: () => ([])
            }
        },
        methods: {
            showTableAssignmentModal() {
                this.tableAssignment = {
                    origin: null,
                    target: null,
                    type: "",
                    assignmentList: []
                };

                this.$nextTick(() => {
                    this.$refs.tableFormRef.clearValidate();
                });

                this.tableAssignmentFormModal.modalVisible = true;
            },
            addTableAssign(assign) {
                this.currentTableAssign = assign;

                this.assignment = {
                    origin: null,
                    target: null
                }
                this.$nextTick(() => {
                    this.$refs.formRef.clearValidate()
                })
                this.assignmentFormModal.modalVisible = true
                this.originFieldsKey = new Date().getTime();
            },
            getComponentType(type) {
                switch (type) {
                    case "string":
                        return "FORM_TEXT_INPUT";
                    case "number":
                        return "FORM_NUMBER_INPUT";
                    default:
                        return "FORM_TEXT_INPUT";
                }
            },
            originChange(component){
                const { currentTableAssign, assignments } = this;
                const COMPONENTTYPE = [component.componentType, 'FORM_TEXT_INPUT', 'FORM_TEXTAREA_INPUT'];
                // 子表的赋值规则
                let tableAssign = assignments.find(item => item.target.uuid === currentTableAssign.target.uuid);
                let options = [];

                if (tableAssign) {
                    // 子表的赋值列表
                    let assignmentList = tableAssign.assignmentList;
                    let targetUuidList = assignmentList.map(item => item.target.uuid);
                    let tableList = getAllSonTableFormItemList(this.formItemList);
                    let table = tableList.find(item => item.uuid === currentTableAssign.target.uuid);

                    if (table) {
                        let tableColumn = table.tableColumn;

                        if (tableColumn && tableColumn.length) {
                            options = tableColumn.filter(item => COMPONENTTYPE.includes(item.componentType) && !targetUuidList.includes(item.uuid));
                        }
                    }
                    
                }

                this.showTargetComponentList = options;
            },
            deleteTableAssign(assgin) {
                if (this.$modalOptEvent) {
                    this.$modalOptEvent.showGlobalModal({
                        visible: true,
                        title: '删除赋值关系',
                        message: '是否确定删除该赋值关系？',
                        okConfig: {
                            title: this.$t('common.confirm'),
                            onOk: () => {
                                this.assignments = this.assignments.filter(item => item.target.uuid !== assgin.target.uuid);
                            }
                        },
                        cancelConfig: {
                            title: this.$t('common.cancel')
                        }
                    })
                }
            },
            deleteTableAssignmentItem(assign, index) {
                if (this.$modalOptEvent) {
                    this.$modalOptEvent.showGlobalModal({
                        visible: true,
                        title: '删除赋值关系',
                        message: '是否确定删除该赋值关系？',
                        okConfig: {
                            title: this.$t('common.confirm'),
                            onOk: () => {
                                const assignment = this.assignments.find(item => item.target.uuid === assign.target.uuid);
                                if (assignment) {
                                    assignment.assignmentList.splice(index, 1);
                                    this.assignments = [...this.assignments];
                                }                                
                            }
                        },
                        cancelConfig: {
                            title: this.$t('common.cancel')
                        }
                    })
                }
            },
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

.parent-assign-list {
    width: 100%;
    border: 1px solid #ebeef5;
    box-sizing: content-box;
    margin-top: 1rem;
    .parent-assign-item {
        box-sizing: border-box;
        padding: 5px;
    }

    .add-table-assign {
        display: flex;
        font-size: 12px;
        cursor: pointer;

        &:hover {
            border-color: rgb(2, 122, 255);
            color: rgb(2, 122, 255);
        }
    }
    .delete-table-assign {
        display: flex;
        justify-content: center;
        font-size: 12px;
        border: 1px dashed rgb(220, 223, 230);
        cursor: pointer;

        &:hover {
            border-color: rgb(2, 122, 255);
            color: rgb(2, 122, 255);
        }
    }
}

</style>
