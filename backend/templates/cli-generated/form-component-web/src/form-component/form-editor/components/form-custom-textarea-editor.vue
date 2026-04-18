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
            type="textarea"
            :autosize="autosize"
            :placeholder="placeholder"
            :resize="resize"
            :rows="rows"
            v-on="$listeners"
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
        name: 'FormCustomTextareaEditor',
        mixins: [EditorFormConfigMixin, FormEditorMixin],
        props: {
            resize: {
                type: String,
                validator(value){
                    ["horizontal", "vertical", "none", "both"].includes(value)
                },
                default: 'none'
            },
            height: {
                type: Number,
                default: 100
            },
            autosize: {
                type: Boolean,
                default: false
            },
            // 默认行数 - 当autosize为true时不生效
            rows: {
                type: Number,
                default: 4
            }
        },
        components: {
            FormCustomSechmaItem
        }
    }
</script>
