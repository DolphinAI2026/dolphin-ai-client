<!--
 * @Author: 可以清心
 * @Description: 
 * @Date: 2023-01-17 10:44:20
 * @LastEditTime: 2023-06-23 20:30:54
-->
<template>
    <form-custom-sechma-item
        class="form-custom-switch-editor"
        :label="label"
        :property="property"
        :config-property="configProperty"
        :showRequired="showRequired"
        :help="help"
        :rules="rules"
    >
        <el-switch
            v-model="formValue"
            v-on="$listeners"
            v-bind="$attrs"
            :disabled="disabled"
            @change="handleChange"
        >
        </el-switch>
    </form-custom-sechma-item>
</template>
<script>
    import EditorFormConfigMixin from '@/mixin/form-config.mixin'
    import FormEditorMixin from '@/mixin/form-editor.mixin'
    import FormCustomSechmaItem from './form-custom-sechma-item.vue'

    export default {
        name: 'FormCustomSwitchEditor',
        mixins: [EditorFormConfigMixin, FormEditorMixin],
        components: {
            FormCustomSechmaItem
        }
    }
</script>

<style lang="scss">
    .form-custom-switch-editor{
        .el-form-item{
            display: flex;
            flex-direction: column;
        }
    }
</style>