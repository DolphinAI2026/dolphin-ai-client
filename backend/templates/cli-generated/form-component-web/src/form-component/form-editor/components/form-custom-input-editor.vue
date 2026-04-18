<template>
    <form-custom-sechma-item
        :label="label"
        :property="property"
        :config-property="configProperty"
        :showRequired="showRequired"
        :help="help"
        :rules="rules"
    >
        <el-input
            v-model="formValue"
            v-on="$listeners"
            v-bind="$attrs"
            :placeholder="placeholder"
            :disabled="disabled"
            :type="type"
            @input="handleChange"
            @cut.native="cutOrCopy($event, 'cut')"
            @copy.native="cutOrCopy($event, 'copy')"
        ></el-input>
    </form-custom-sechma-item>
</template>
<script>
    import EditorFormConfigMixin from '@/mixin/form-config.mixin'
    import FormEditorMixin from '@/mixin/form-editor.mixin'
    import FormCustomSechmaItem from './form-custom-sechma-item.vue'

    export default {
        name: 'FormCustomInputEditor',
        mixins: [EditorFormConfigMixin, FormEditorMixin],
        components: {
            FormCustomSechmaItem
        }
    }
</script>