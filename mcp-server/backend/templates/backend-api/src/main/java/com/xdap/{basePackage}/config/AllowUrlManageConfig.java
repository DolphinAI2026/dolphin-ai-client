package com.xdap.{basePackage}.config;

import com.xdap.api.moudle.custom.AllowUrlManage;
import org.springframework.stereotype.Component;

import java.util.HashSet;
import java.util.Set;

@Component
public class AllowUrlManageConfig implements AllowUrlManage {

    @Override
    public Set<String> getCustomAllowUrls() {
        Set<String> urlSet = new HashSet<>();
        return urlSet;
    }
}
