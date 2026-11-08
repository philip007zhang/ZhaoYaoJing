# 架构与数据流

```mermaid
flowchart LR
  UI[本机浏览器] --> HTTP[local_app.py]
  HTTP --> Worker[单个隔离子进程]
  Worker --> Scan[weekly_chat.py]
  Scan --> Cache[同群同周复用]
  Scan --> WX[微信 UI / wxautox4]
  WX --> Store[JSON包与SQLite]
  Store --> Export[history_store.py流式导出]
  Cache --> Analysis[gemini_analysis.py]
  Export --> Analysis
  Analysis --> Media[可选媒体解读]
  Analysis --> Gemini[Gemini API]
  Media --> Gemini
  Gemini --> Report[连续文本与HTML]
  Report --> UI
```

本地服务用无shell参数数组调用原有命令，不维护第二套采集逻辑。提示词写入忽略提交的.local目录；密钥不进入命令参数。锁保证单任务，日志缓冲限制1500行，浏览器定时轮询。

采集固定请求数量，goback=False保持历史位置。时间分隔符按块整理，允许UI加载造成的回退。SQLite按包逆序导出；部分重叠仍需审查，不依赖会变化的UI ID删除内容相同的真实发言。

分析采用分片候选发现与最终汇总，引用尽力校验而不阻断正文。恢复分片先比对消息范围。视频或网页作者观点不等于分享者观点，更不代表群共识。
