package {basePackage}.client;

import com.alibaba.fastjson.JSONObject;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;

/**
 * 示例 FeignClient - 用于调用外部系统接口
 *
 * 规范要点：
 * 1. 放在 {basePackage}.client 包下
 * 2. 使用 @FeignClient 注解，url 通过配置属性注入
 * 3. name 属性为客户端标识，url 使用 ${property:defaultValue} 格式
 * 4. 请求头使用 @RequestHeader 注入，请求体使用 @RequestBody
 * 5. consumes 指定为 APPLICATION_JSON_UTF8_VALUE
 * 6. 相关配置需在 application.properties 中添加对应的 url 配置
 */
@FeignClient(name = "exampleClient", url = "${example.api.url:http://localhost:8080}")
public interface ExampleFeignClient {

    /**
     * 示例接口 - 同步数据
     *
     * @param token     鉴权 token
     * @param timestamp 时间戳
     * @param tenantId  租户ID
     * @param request   请求体
     * @return 响应结果
     */
    @PostMapping(value = "/api/data/sync", consumes = MediaType.APPLICATION_JSON_UTF8_VALUE)
    JSONObject syncData(@RequestHeader("xdaptoken") String token,
                        @RequestHeader("xdaptimestamp") long timestamp,
                        @RequestHeader("xdaptenantid") String tenantId,
                        @RequestBody JSONObject request);

    /**
     * 示例接口 - 查询数据
     *
     * @param token     鉴权 token
     * @param timestamp 时间戳
     * @param tenantId  租户ID
     * @param request   请求体
     * @return 响应结果
     */
    @PostMapping(value = "/api/data/query", consumes = MediaType.APPLICATION_JSON_UTF8_VALUE)
    JSONObject queryData(@RequestHeader("xdaptoken") String token,
                         @RequestHeader("xdaptimestamp") long timestamp,
                         @RequestHeader("xdaptenantid") String tenantId,
                         @RequestBody JSONObject request);
}
