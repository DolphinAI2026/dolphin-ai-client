package com.xdap.{basePackage}.config;

import com.definesys.mpaas.query.MpaasQuery;
import com.xdap.api.constant.ApplicationConstant;
import com.xdap.api.constant.DataSourceName;
import com.xdap.runtime.service.RuntimeDatasourceService;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class DatasourceUtil {

    private final RuntimeDatasourceService runtimeDatasourceService;

    @Value("${apaas.single.tenantId}")
    private String tenantSchema;

    public MpaasQuery buildDefaultMpaasQuery() {
        return runtimeDatasourceService.buildTenantMpaasQuery(DataSourceName.MYSQL_PREFIX + tenantSchema);
    }

    public MpaasQuery buildPlatformMpaasQuery() {
        return runtimeDatasourceService.buildTenantMpaasQuery(ApplicationConstant.AdminSourceName);
    }

    public MpaasQuery buildDefaultActivitiMpaasQuery() {
        return runtimeDatasourceService.buildTenantMpaasQuery("xdap_activiti_" + tenantSchema);
    }
}
