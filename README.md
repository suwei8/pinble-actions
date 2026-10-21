# pinble-actions

Scheduled GitHub Actions runner.

Three workflows poll a small HTTP feed and maintain a private dataset:

- **collect** — daily incremental collection job
- **snipe** — publish-window watcher
- **forecast** — periodic statistics job

All inputs, credentials and outputs live in a separate private repository;
this repo only contains workflow definitions.


## 3dtong-v2 事件驱动预测

数据采集工作流只有在 **`data/k3_full_history.csv` 实际改变并成功推送私有 `pinble-data` 之后**，才通过 GitHub `repository_dispatch` 通知公开 `suwei8/3dtong-v2` 尝试下一期预测。事件只发送来源提交 SHA，不含私有CSV或开奖号码。

需要在本仓 **Settings → Secrets and variables → Actions** 新增 `PREDICT_DISPATCH_TOKEN`：推荐 fine-grained PAT，仅授权 `suwei8/3dtong-v2` 仓库 **Contents: Read and write**，用于触发 repository_dispatch。此令牌不需要访问 `pinble-data`，切勿放进文件。未配置时，采集继续成功、事件步骤提示 warning，目标仓定时任务继续兜底。

请在 [每日增量采集](.github/workflows/collect.yml) 的事件通知步骤及目标仓的 GitHub Actions 页面验证首次真实事件。工作流已提交不等于跨仓库事件成功投递。
