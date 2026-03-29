package {basePackage}.service.impl;

import com.definesys.mpaas.common.http.Response;
import com.definesys.mpaas.query.db.PageQueryResult;
import {basePackage}.dao.ExampleDao;
import {basePackage}.dto.ExampleCreateRequest;
import {basePackage}.dto.ExampleQueryRequest;
import {basePackage}.dto.PageRequest;
import {basePackage}.enums.ExampleExceptionEnum;
import {basePackage}.pojo.Example;
import {basePackage}.service.ExampleService;
import com.xdap.motor.entity.SnowflakeIdWorker;
import com.xdap.motor.exception.XDapBizException;
import com.xdap.motor.vo.PageRespHelper;
import com.xdap.runtime.service.RuntimeAppContextService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * 示例服务实现类
 *
 * 规范要点：
 * 1. 实现类放在 {basePackage}.service.impl 包下
 * 2. 使用 @Service 注解
 * 3. 使用 @RequiredArgsConstructor 构造器注入，依赖字段声明为 final
 * 4. 使用 @Slf4j 输出日志
 * 5. Service 层只负责业务逻辑编排，数据库操作通过 Dao 层
 * 6. 业务异常使用 XDapBizException + 异常枚举抛出
 * 7. 需要事务的方法使用 @DAPTransaction 注解
 * 8. 新增记录时必须调用 setBaseField() 初始化系统字段
 */
@RequiredArgsConstructor
@Service
@Slf4j
public class ExampleServiceImpl implements ExampleService {

    private final ExampleDao exampleDao;
    private final SnowflakeIdWorker snowflakeIdWorker;
    private final RuntimeAppContextService runtimeAppContextService;

    @Value("${apaas.single.tenantId}")
    private String tenantId;

    @Override
    public Response pageQuery(PageRequest<ExampleQueryRequest> request) {
        PageQueryResult pageQueryResult = exampleDao.pageQuery(
                request.getPage(), request.getPageSize(), request.getCondition());
        return Response.ok().table(pageQueryResult.getResult()).setTotal(pageQueryResult.getCount());
    }

    @Override
    public Response getDetail(String id) {
        Example example = exampleDao.getOneById(id);
        if (example == null) {
            throw new XDapBizException(ExampleExceptionEnum.EXAMPLE_NOT_EXISTS, id);
        }
        return Response.ok().data(example);
    }

    @Override
    public Response create(ExampleCreateRequest request) {
        log.info("创建示例, name: {}", request.getName());
        Example example = new Example();
        BeanUtils.copyProperties(request, example);

        // 通过 RuntimeAppContextService 获取当前登录用户ID
        String currentUserId = runtimeAppContextService.getCurrentUserId();

        // 新增记录时必须调用 setBaseField() 初始化系统字段
        // 参数：owner(创建者)、formId(表单ID，固定值，需业务方提供)、snowflakeIdWorker(雪花ID生成器)、tenantId(租户ID)
        // ⚠️ formId 是一个固定值，开发前需要向业务方确认获取
        example.setBaseField(currentUserId, "formId", snowflakeIdWorker, tenantId);

        exampleDao.insert(example);
        return Response.ok().data(example);
    }

    @Override
    public Response update(ExampleCreateRequest request) {
        Example existing = exampleDao.getOneById(request.getId());
        if (existing == null) {
            throw new XDapBizException(ExampleExceptionEnum.EXAMPLE_NOT_EXISTS, request.getId());
        }
        BeanUtils.copyProperties(request, existing);
        exampleDao.updateById(existing);
        return Response.ok().data(existing);
    }

    @Override
    public Response delete(String id) {
        Example existing = exampleDao.getOneById(id);
        if (existing == null) {
            throw new XDapBizException(ExampleExceptionEnum.EXAMPLE_NOT_EXISTS, id);
        }
        exampleDao.deleteById(id);
        return Response.ok();
    }
}
