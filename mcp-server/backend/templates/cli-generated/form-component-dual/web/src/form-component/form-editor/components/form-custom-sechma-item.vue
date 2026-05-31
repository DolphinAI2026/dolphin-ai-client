<template>
    <div class="sechma-form-item">
        <!-- 当 element-ui 有这个类名的时候会触发必填提醒，显然不必多此一举 -->
        <!--
            el-form 绑定了对象 对象里面有一个属性 configProperty 这个值是在组件的配置文件里面写的固定是customComponentConfig 里面有自定义的自开发属性
            详细看 el-form-item 多层级绑定 rules
        -->
        <el-form-item
            :label="label || property"
            :prop="configProperty + '.' + property"
            :class="{
                'is-required': showRequired
            }"
            :rules="rules"
        >
            <template v-slot:label>
                <span class="sechma-form-item__label">{{ label }}</span>
                <el-tooltip v-if="help.length > 0" placement="top">
                    <template v-slot:content>
                        <ul class="sechma-form-item__help">
                            <template v-for="row in help">
                                <li :key="row" class="sechma-form-item__text">
                                    <a v-if="row.includes('https://')" :href="row.split('[]')[1]" target="_blank" style="color: #DC143C;">{{ row.split('[]')[0] }}</a>
                                    <span v-else>{{ row }}</span>
                                </li>
                            </template>
                        </ul>
                    </template>
                    <x-svg-icon class="pointer" name="helper-icon"></x-svg-icon>
                </el-tooltip>
            </template>
            <slot></slot>
        </el-form-item>
    </div>
</template>

<script>
    export default {
        name: 'FormCustomSechmaItem',
        props: {
            label: {
                type: String,
                required: true
            },
            property: {
                type: String,
                required: true
            },
            configProperty: {
                type: String,
                required: true
            },
            showRequired: {
                type: Boolean,
                default: false
            },
            rules: {
                type: Array,
                default: () => []
            },
            help: {
                type: Array,
                default: () => []
            }
        }
    }
</script>