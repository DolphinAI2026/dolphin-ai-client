const FormEditorMixin = {
    props: {
        label: {
            type: String
        },
        property: {
            type: String,
            required: true
        },
        showRequired: {
            type: Boolean,
            default: false
        },
        placeholder: {
            type: String,
            default: '请输入'
        },
        encryption: {
            type: Boolean,
            default: false
        },
        isAllowCutOrCopy: {
            type: Boolean,
            default: true
        },
        help: {
            type: Array,
            default: () => []
        },
        i18nString: {
            type: String,
            default: 'common.formPlaceholder.input'
        }
    },
    data() {
        return {
            formValue: '',
            widgetRules: null
        }
    },
    created() {
        const {property, encryption} = this;
        if(property){
            if(encryption){
                // 加密
                this.formValue = this.getEncryptionProperty(this.componentConfig && this.componentConfig.customComponentConfig[property]);
            }else{
                this.formValue = this.componentConfig && this.componentConfig.customComponentConfig[property];
            }
        }
    },
    computed: {
        rules(){
            let rules = [];

            if(this.showRequired){
                rules.push(
                    this._validate(
                        'required',
                        `${this.$t(this.i18nString)}${this.label}`
                    )
                )
            }

            if(this.widgetRules){
                rules.push(...this.widgetRules);
            }

            return rules;
        }
    },
    methods: {
        handleChange(value) {
            const {property} = this;
            this.componentConfig.customComponentConfig[property] = value
        },
        getEncryptionProperty(key){
            if(key && key.trim()){
                let length = Math.floor(key.length / 4);

                if(length === 0){
                    return Array.from(new Array(key.length)).map(() => ('*')).join("");
                }

                let headString = key.substr(0, length);
                let footerString = key.substr(-length);

                let middleString = Array.from(new Array(key.length - (2 * length))).map(() => ('*')).join("");

                return headString + middleString + footerString;
            }else{
                return key;
            }
        },
        cutOrCopy($event, type){
            if(!this.isAllowCutOrCopy){
                // 不允许复制或剪切
                $event.preventDefault();
                $event.stopPropagation();
                this.$message({
                    type: 'warning',
                    message: this.$t('common.request.notAllowed') + (type === 'cut' ? this.$t('common.request.cut') : this.$t('common.request.copy'))
                })
            }else{
                this.$message({
                    type: 'success',
                    message: this.$t('downloadFile.copySuccess')
                })
            }
        },
        getI18nString(code, object){
            if(object){
                return this.$t(code, object);
            }else{
                return this.$t(code);
            }
        }
    }
}

export default FormEditorMixin;