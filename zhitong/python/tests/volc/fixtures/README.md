# zt-volc 测试夹具

这些文件是**按官方 API 字段手写的合成输出**，不是从真实 ve 抓取的录制：沙箱连不上火山引擎，字段名与嵌套取自
volcengine-go-sdk（`service/ecs`、`service/vpc`）的响应结构，外层是 `ve` 文档约定的 `{"ResponseMetadata", "Result"}`。
IP 是任意公网地址示例，实例与安全组 ID 都是虚构的。拿到真实 `ve` 之后，用同样的文件名
重新录制替换即可（`ve ecs DescribeInstances --output json > ecs.DescribeInstances.json`，先脱敏）。
`tosutil.*.txt` 的行格式尤其是猜测，真实格式未核实。
