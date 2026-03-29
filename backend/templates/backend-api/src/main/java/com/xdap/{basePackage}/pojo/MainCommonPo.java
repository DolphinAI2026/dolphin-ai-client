package com.xdap.{basePackage}.pojo;

import com.definesys.mpaas.query.annotation.Column;
import com.xdap.api.moudle.base.entity.NoTenBasePojo;
import com.xdap.motor.entity.SnowflakeIdWorker;
import lombok.Data;
import org.springframework.stereotype.Component;

import java.util.Date;

@Component
@Data
public class MainCommonPo extends NoTenBasePojo {

    private String id;

    @Column("document_id")
    private String documentId;

    @Column("tab_doc_id")
    private String tabDocId;

    private String status;

    @Column("tenant_id")
    private String tenantId;

    @Column("form_id")
    private String formId;

    @Column("process_id")
    private String processId;

    @Column("approver_id")
    private String approverId;

    /**
     * 初始化系统字段（新增记录时调用）
     *
     * @param owner             数据拥有者/创建者
     * @param formId            表单ID
     * @param snowflakeIdWorker 雪花ID生成器
     * @param tenantId          租户ID
     */
    public void setBaseField(String owner, String formId, SnowflakeIdWorker snowflakeIdWorker, String tenantId) {
        this.setId(snowflakeIdWorker.nextId());
        this.setOwner(owner);
        this.setCreatedBy(owner);
        this.setLastUpdatedBy(owner);
        this.setCreationDate(new Date());
        this.setLastUpdateDate(new Date());
        this.setFormId(formId);
        if (this.documentId == null) {
            this.setDocumentId(snowflakeIdWorker.nextId());
        }
        this.setStatus("COMPLETED");
        this.setTenantId(tenantId);
        this.setObjectVersionNumber(1);
    }
}
