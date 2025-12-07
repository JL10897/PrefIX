# 批量用户模拟方案（OpenAI）

- 数据源：`/Users/JL/Desktop/Agent_IX_Personalization/Processing/BFCL_v3_multi_turn_long_context_rewrite_filled.json`（按 id 后缀数字筛选 `--start-index`~`--end-index`）。
- 历史存储：`bfcl_eval/user_simulator/history/<model_sanitized>/<entry_id>.json`，JSON 数组，保留 user/assistant/tool 消息；每轮写回。
- Persona：从 `bfcl_eval/user_simulator/persona_prompt.md` 解析；`--persona` 指定，未提供则不加 persona。
- Prompt 结构（模拟器）：固定声明 → persona 描述/示例（若有） → `simulator_prompt.md` → `<dialog_history>`（空为 []） → 高阶指令 → 终止提醒 → “Return only the next user turn message.”
- 终止策略：唯一终止 token `<END_SIMULATION>`；用户消息含该 token 即标记完成，但 BaseHandler 仍需让当前轮模型/工具运行完再结束 entry。
- 数据流：BaseHandler 持续循环；调用模拟器生成 user 消息 → 追加到历史（内存+文件）→ 发给模型 → 解析/执行工具并追加到历史 → 若检测终止 token，当前轮结束后终止 entry。若历史已含终止 token，跳过 entry。
- 安全：保留 `MAXIMUM_STEP_LIMIT`；若未出终止且超限则强制终止并记录原因；persona 不存在则忽略。`OPENAI_API_KEY` 从 `.env` 读取。
- Edge cases：高阶指令为空时模型可能生成泛化消息；未上限情况下模型不出终止可能长循环，可后续调优。
