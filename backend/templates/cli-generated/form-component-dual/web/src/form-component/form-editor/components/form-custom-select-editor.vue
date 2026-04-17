<template>
    <form-custom-sechma-item
        :label="label"
        :property="property"
        :config-property="configProperty"
        :showRequired="showRequired"
        :help="help"
        :rules="rules"
    >
        <x-select
            v-model="formValue"
            v-on="$listeners"
            v-bind="$attrs"
            :disabled="disabled"
            :multiple="multiple"
            :placeholder="placeholder"
            :options="options"
            @change="handleChange"
        ></x-select>
    </form-custom-sechma-item>
</template>
<script>
    import EditorFormConfigMixin from '@shared/mixin/form-config.mixin'
    import FormEditorMixin from '@shared/mixin/form-editor.mixin'
    import FormCustomSechmaItem from './form-custom-sechma-item.vue'

    export default {
        name: 'FormCustomSelectEditor',
        mixins: [EditorFormConfigMixin, FormEditorMixin],
        props: {
            options: {
                type: Array,
                default: () => []
            },
            multiple: {
                type: Boolean,
                default: false
            }
        },
        components: {
            FormCustomSechmaItem
        }
    }
</script>