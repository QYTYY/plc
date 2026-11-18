# 模块7：本地持久化与人工复核

模块7提供可运行的本地管理服务和命令行入口，暂未提供 Web 页面。
业务库和 LangGraph 检查点分别存放在 `knowledge_db/management/`，该目录由
现有 `.gitignore` 排除。SQLite 适用于目前的单机阶段；服务层权限不替代操作系统文件权限。

## 数据与流程

- `business.sqlite`：用户、会话、项目成员、案件快照、专家反馈、正式规则版本和审计。
- `checkpoints.sqlite`：LangGraph 节点检查点与人工审核中断。
- `discussion.jsonl`：每轮评审记录；`reports/`：审核后的中文 JSON 报告。
- 用户密码使用独立随机盐和 PBKDF2-SHA256；数据库只保存会话令牌摘要，会话8小时过期。
- 每个案件使用项目编号和随机案件编号组成独立 `thread_id`。

```text
创建案件 → 输入整理 → 加载规则 → 确定性检查 → 三轮讨论
                                              ↓
                               需要复核？→ 持久化暂停
                                              ↓
                               专家登录、确认并填写原因
                                              ↓
                                    恢复 → 保存最终报告
```

规则不合规、证据不足、意见分歧、未确认低置信度证据、缺失信息、冲突以及
没有适用规则都会进入人工审核。低置信度证据必须通过明确证据编号确认；
未确认的证据会继续保留复核标记。人工结论和原因单独保存，不会覆盖原始规则结果和三轮意见。

## 使用

在项目根目录执行。密码通过交互输入，不出现在命令行参数和操作历史中。

```powershell
python scripts/manage_assessments.py init-user admin
python scripts/manage_assessments.py --user admin create-project "PLC安全评估"
python scripts/manage_assessments.py --user admin create-user expert1
python scripts/manage_assessments.py --user admin add-member 项目编号 用户编号 expert
python scripts/manage_assessments.py --user admin publish-rule 项目编号 rule.json
python scripts/manage_assessments.py --user admin create-case 项目编号 case.json
python scripts/manage_assessments.py --user admin run 案件编号
python scripts/manage_assessments.py --user expert1 status 案件编号
python scripts/manage_assessments.py --user expert1 review 案件编号 --conclusion 不合规 --reason "已核对设备当前配置" --confirm E1
python scripts/manage_assessments.py --user admin list-cases 项目编号
python scripts/manage_assessments.py --user admin audit
```

首个用户为管理员；之后创建用户必须管理员登录。普通成员可以创建和运行案件，
专家可以复核，规则管理员可以发布规则，项目所有者可以管理项目成员并审核。
系统管理员拥有管理权限。普通成员不能向案件自行注入未经批准的规则。
创建案件时未指定规则，会加载本项目最新发布版本，并固定保存到案件快照。
同一规则同一版本不能覆盖；修订时必须使用新版本。

`case.json` 最小离线样例（演示规则由项目所有者提供，不代表真实标准条款）：

```json
{
  "task": "检查多因素认证配置",
  "evidence": [{
    "evidence_id": "E1", "source": "config.txt", "location": "line_1",
    "content": "mfa_enabled=false", "evidence_type": "configuration", "confidence": 1.0
  }],
  "rules": [{
    "rule_id": "DEMO-MFA", "version": "demo-v1", "requirement": "演示：应启用多因素认证",
    "risk_level": "high", "constraint": {"field": "mfa_enabled", "operator": "==", "expected": true}
  }]
}
```

`run --offline` 使用离线 Reviewer 验证流程，不调用真实大模型。真实运行使用根目录
`.env` 中的 DeepSeek 配置，并按索引清单加载已有本地 Chroma，缺少知识索引时明确报错。
案件状态内部使用 `created / running / awaiting_review / completed / failed`。

## 失败与恢复

普通节点失败会将案件标记为 `failed`，再次 `run` 从最后成功节点恢复。
人工审核中断在进程退出后仍然保留，再次 `review` 即可继续。
三轮讨论当前整体属于一个 LangGraph 节点；若该节点内部失败，会重新执行该节点，
已经写入的讨论 JSONL 可能包含此前尝试，暂不支持从某一轮中的单个角色恢复。

如果进程被强制结束，案件可能保留 `running` 状态。确认原进程已停止后，所有者可执行：

```powershell
python scripts/manage_assessments.py --user admin recover 案件编号 --confirm-stopped
```

不得在原任务仍运行时回收案件。当前实现未包含分布式工作进程和自动租约回收。
审计日志采用事务追加，服务不提供修改和删除接口；它不是防数据库管理员篡改的外部审计系统。

## 依赖与验证

使用官方维护的 `langgraph-checkpoint-sqlite` 保存 LangGraph 原生检查点，避免自行实现
序列化和恢复协议。依赖记录在 `plc_compliance/llm_requirements.txt`。
其余业务存储、密码散列和会话机制使用 Python 标准库。

```powershell
uv pip install --python python -r plc_compliance/llm_requirements.txt
python -m unittest discover -s tests/unit_tests -p test_management.py -v
```

增加了检查点和审核能力的 `build_assessment_graph` 参数是可选的关键字参数，
旧调用方式保持兼容。需要持久化人工复核时，建议使用 `AssessmentApplication`，
它负责关闭数据库连接并执行权限检查。不要把底层图直接暴露为未认证的公共接口。
