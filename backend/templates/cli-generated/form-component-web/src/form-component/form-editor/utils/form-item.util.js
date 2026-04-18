function getAllFormItemList(formItemList){
    let formList = [];

    formItemList.forEach(form => {
        if(form.children && form.children.length){
            if(form.componentType === 'FORM_WIDGET_SON_TABLE'){
                formList.push(form);
            }
            formList.push(...getAllFormItemList(form.children))
        }else{
            formList.push(form);
        }
    })

    return formList;
}

function getAllSonTableFormItemList(formItemList) {
    let formList = [];

    formItemList.forEach(form => {
        if(form.componentType === 'FORM_WIDGET_SON_TABLE'){
            formList.push(form);
        }
    });

    return formList;
}

function getAllFormItemListExcludeSelf(formItemList, uuid) {
    let formList = [];

    formItemList.forEach(form => {
        if(form.children && form.children.length){
            if(form.componentType === 'FORM_WIDGET_SON_TABLE' && form.uuid !== uuid){
                formList.push(form);
            }
            formList.push(...getAllFormItemListExcludeSelf(form.children))
        }else{
            if (form.uuid !== uuid) {
                formList.push(form);
            }
        }
    })
    
    return formList;
}

function getAllFormItemListExcludeIsInTableAndSelf(formItemList, self){
    let formList = [];

    formItemList.forEach(form => {
        if(form.children && form.children.length){
            formList.push(...getAllFormItemListExcludeIsInTableAndSelf(form.children, self))
        }else{
            if(!form.isInTable && form.uuid !== self.uuid){
                formList.push(form);
            }
        }
    })

    return formList;
}

function getAllFormItemListExcludeSonTableAndIncludeComponentType(formItemList, componentTypes){
    let formList = [];

    formItemList.forEach(form => {
        // 排除子表
        if(form.componentType !== 'FORM_WIDGET_SON_TABLE'){
            if(form.children && form.children.length){
                formList.push(...getAllFormItemListExcludeSonTableAndIncludeComponentType(form.children, componentTypes));
            }else{
                if(componentTypes.includes(form.componentType)){
                    formList.push(form);
                }
            }
        }
    })

    return formList;
}

function getAllFormItemListExcludeTable(formItemList){
    let formList = [];

    formItemList.forEach(form => {
        if(form.children && form.children.length){
            // 有包含组件
            if(form.componentType !== 'FORM_WIDGET_SON_TABLE'){
                // 不是子表
                formList.push(...getAllFormItemListExcludeTable(form.children));
            }else{
                // 是子表，直接放入吧
                formList.push(form);
            }
        }else{
            formList.push(form);
        }
    })

    return formList;
}

function getAllFormListByComponentType(formItemList, componentType) {
    let formList = [];

    formItemList.forEach(form => {
        if (form.children && form.children.length) {
            if (form.componentType === componentType) {
                formList.push(form);
            }
            formList.push(...getAllFormListByComponentType(form.children, componentType));
        } else {
            if (form.componentType === componentType) {
                formList.push(form);
            }
        }
    });

    return formList;
}

export {
    getAllFormItemList,
    getAllFormItemListExcludeIsInTableAndSelf,
    getAllFormItemListExcludeSonTableAndIncludeComponentType,
    getAllFormItemListExcludeTable,
    getAllFormListByComponentType,
    getAllFormItemListExcludeSelf,
    getAllSonTableFormItemList,
}