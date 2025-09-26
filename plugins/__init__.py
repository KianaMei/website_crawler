"""
低代码运行时插件包。

每个模块应导出入口函数 `handler(args: Args[Input]) -> Output`：
- `Args` 来自运行时（runtime）
- `Input`/`Output` 为对应工具的输入/输出数据模型
"""
