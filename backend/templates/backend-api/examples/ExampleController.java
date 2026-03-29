package {basePackage}.controller;

import com.definesys.mpaas.common.http.Response;
import {basePackage}.dto.ExampleCreateRequest;
import {basePackage}.dto.ExampleQueryRequest;
import {basePackage}.dto.PageRequest;
import {basePackage}.service.ExampleService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

/**
 * 示例控制器
 *
 * 规范要点：
 * 1. 使用 @RestController + @RequestMapping，路径必须以 /custom 开头
 * 2. 使用 @RequiredArgsConstructor 构造器注入，禁止 @Autowired
 * 3. Controller 只负责接收请求和返回结果，禁止编写业务逻辑
 * 4. 只允许调用 Service 层，禁止直接调用 Dao 层
 * 5. 返回类型统一使用 Response
 * 6. 需要参数校验时使用 @Validated 注解
 */
@RequestMapping("/custom/example")
@RestController
@RequiredArgsConstructor
@Slf4j
public class ExampleController {

    private final ExampleService exampleService;

    /**
     * 分页查询
     */
    @PostMapping("/query")
    public Response query(@RequestBody PageRequest<ExampleQueryRequest> request) {
        return exampleService.pageQuery(request);
    }

    /**
     * 根据ID查询详情
     */
    @GetMapping("/detail")
    public Response detail(@RequestParam("id") String id) {
        return exampleService.getDetail(id);
    }

    /**
     * 新增 — 使用 @Validated 触发 DTO 中的 @NotNull/@NotBlank 校验
     */
    @PostMapping("/create")
    public Response create(@Validated @RequestBody ExampleCreateRequest request) {
        return exampleService.create(request);
    }

    /**
     * 更新
     */
    @PostMapping("/update")
    public Response update(@Validated @RequestBody ExampleCreateRequest request) {
        return exampleService.update(request);
    }

    /**
     * 删除
     */
    @PostMapping("/delete")
    public Response delete(@RequestParam("id") String id) {
        return exampleService.delete(id);
    }
}
