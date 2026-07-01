<template>
  <div v-if="available" class="aiops-widget" :class="{ embedded }" :style="embedded ? null : fabStyle">
    <transition name="aiops-panel">
      <div v-if="embedded || visible" class="aiops-layer" :class="{ embedded }">
        <button v-if="!embedded" type="button" class="aiops-backdrop" @click="closePanel" />

        <div class="aiops-panel" :class="{ embedded }">
          <div class="aiops-panel-header">
            <div class="header-copy">
              <div class="aiops-title-row">
                <img :src="botAvatar" alt="AIOps bot" class="aiops-header-avatar" />
                <div class="aiops-title">AIOps 智能助手</div>
                <span class="header-badge">{{ bootstrap.provider?.model || bootstrap.provider?.name || '未配置模型' }}</span>
                <span v-if="!bootstrap.runtime?.allow_action_execution" class="header-badge runtime safe">
                  {{ runtimeLabel }}
                </span>
                <span class="aiops-subtitle">
                  {{ effectiveAnalysisOnly ? '当前仅分析，不会生成待执行动作。' : (bootstrap.welcome_message || '你好，我可以帮你结合平台上下文查询资源、根因分析、生成待执行任务等。') }}
                </span>
              </div>
            </div>
            <div class="aiops-header-actions">
              <el-button v-if="!embedded" size="small" class="aiops-toolbar-btn" @click="closePanel">
                <el-icon><Fold /></el-icon>
                <span>收起</span>
              </el-button>
            </div>
          </div>

          <div class="aiops-panel-body">
            <aside class="aiops-session-list">
              <div class="session-list-head">
                <div class="session-head-title">
                  <span class="session-list-title">会话历史</span>
                </div>
                <el-button size="small" class="aiops-toolbar-btn" @click="handleCreateSession">
                  <el-icon><Plus /></el-icon>
                  <span>新建</span>
                </el-button>
              </div>
              <div
                v-for="session in sessions"
                :key="session.id"
                class="aiops-session-item"
                :class="{ active: currentSessionId === session.id }"
              >
                <button
                  type="button"
                  class="session-select-btn"
                  @click="selectSession(session.id)"
                >
                  <el-tooltip
                    :disabled="!shouldShowSessionTooltip(session.title)"
                    effect="light"
                    placement="right"
                    :show-after="180"
                    popper-class="aiops-session-tooltip"
                  >
                    <span class="session-title">{{ session.title || '新会话' }}</span>
                    <template #content>
                      <div class="aiops-session-tooltip-card">
                        <div class="aiops-session-tooltip-title">{{ session.title || '新会话' }}</div>
                      </div>
                    </template>
                  </el-tooltip>
                </button>
                <el-button
                  class="session-delete-btn"
                  circle
                  text
                  :disabled="loading.deleteSession === session.id"
                  @click.stop="handleDeleteSession(session)"
                >
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
              <div v-if="!sessions.length" class="session-empty">暂无历史会话</div>
            </aside>

            <section class="aiops-chat-main">
              <div class="chat-toolbar">
                <div class="chat-toolbar-left">
                  <button v-if="isMobile" type="button" class="toolbar-chip" @click="mobileSessionVisible = true">
                    会话 {{ sessions.length }}
                  </button>
                  <div class="session-indicator">
                    <span class="session-indicator-label">{{ currentSession?.title || '新会话' }}</span>
                  </div>
                  <span class="environment-chip" :class="{ empty: !currentEnvironmentName }">
                    {{ currentEnvironmentName ? `环境：${currentEnvironmentName}` : '未指定环境' }}
                  </span>
                  <label class="analysis-toggle">
                    <span>只分析</span>
                    <el-switch v-model="analysisSwitchValue" size="small" :disabled="forcedAnalysisOnly" />
                  </label>
                </div>
                <div class="chat-toolbar-right">
                  <span class="toolbar-hint">
                    {{ analysisHintText }}
                  </span>
                </div>
              </div>

              <div class="quick-palette">
                <div v-if="!messages.length && bootstrap.suggested_questions?.length" class="aiops-quick-questions">
                  <button
                    v-for="item in bootstrap.suggested_questions"
                    :key="item"
                    type="button"
                    class="quick-chip"
                    @click="applySuggestedQuestion(item)"
                  >
                    {{ item }}
                  </button>
                </div>
              </div>

              <div class="message-stage">
                <div ref="messageListRef" class="aiops-message-list" v-loading="loading.messages">
                  <div v-if="!renderMessages.length" class="message-empty">
                    <div class="empty-title">可以直接问我</div>
                    <div class="empty-copy">资源现状、未确认告警、关联分析、任务草稿，我都会优先给出平台内证据。</div>
                  </div>

                  <div
                    v-for="(message, index) in renderMessages"
                    :key="message.localKey || message.id"
                    class="message-item"
                    :class="[message.role, { pending: message.pending || isMessageProcessing(message) }]"
                  >
                    <div class="message-meta">
                      <span class="message-role">{{ message.role === 'user' ? '你' : '智能助手' }}</span>
                      <span class="message-time">{{ formatDateTime(message.created_at) }}</span>
                    </div>

                    <div class="message-bubble">
                      <div
                        v-if="message.role === 'assistant' && shouldShowProcessCard(message)"
                        class="analysis-process-card"
                        :class="{ active: isMessageProcessing(message) }"
                      >
                        <div class="analysis-process-head">
                          <div class="analysis-process-headline">
                            <div class="analysis-process-title">思考过程</div>
                            <div class="analysis-process-inline-summary">{{ getProcessSummary(message) }}</div>
                          </div>
                          <div class="analysis-process-actions">
                            <span class="analysis-process-status" :class="getProcessingStatus(message)">{{ getProcessingStatusLabel(message) }}</span>
                            <button type="button" class="analysis-process-toggle" @click="toggleProcessExpanded(message)">
                              {{ isProcessExpanded(message) ? '收起' : '展开' }}
                            </button>
                          </div>
                        </div>
                        <div v-show="isProcessExpanded(message)" class="analysis-process-content">
                          <div v-if="message.metadata?.processing_text" class="analysis-process-summary">
                            {{ message.metadata.processing_text }}
                          </div>
                          <div v-if="message.metadata?.processing_steps?.length" class="analysis-process-list">
                            <div
                              v-for="(step, stepIndex) in message.metadata.processing_steps"
                              :key="`${message.id || message.localKey}-step-${stepIndex}`"
                              class="analysis-process-item"
                            >
                              <span class="analysis-process-dot" :class="step.status || 'completed'" />
                              <div class="analysis-process-body">
                                <div class="analysis-process-item-head">
                                  <strong>{{ step.title }}</strong>
                                  <span>{{ formatProcessTime(step.timestamp) }}</span>
                                </div>
                                <div v-if="step.detail" class="analysis-process-item-detail">{{ step.detail }}</div>
                              </div>
                            </div>
                          </div>
                          <div v-if="message.metadata?.tool_events?.length" class="tool-event-list">
                            <div
                              v-for="(event, eventIndex) in message.metadata.tool_events"
                              :key="`${message.id || message.localKey}-tool-${eventIndex}`"
                              class="tool-event-item"
                            >
                              <span class="tool-event-name">{{ event.name }}</span>
                              <span class="tool-event-detail">{{ event.detail }}</span>
                            </div>
                          </div>
                        </div>
                      </div>

                      <div v-if="isAssistantErrorMessage(message)" class="message-error-card">
                        <div class="message-error-head">
                          <span class="message-error-badge">问答未完成</span>
                          <span v-if="getAssistantErrorDisplay(message).tag" class="message-error-tag">
                            {{ getAssistantErrorDisplay(message).tag }}
                          </span>
                        </div>
                        <div class="message-error-title">{{ getAssistantErrorDisplay(message).title }}</div>
                        <div class="message-error-desc">{{ getAssistantErrorDisplay(message).description }}</div>
                        <div v-if="getAssistantErrorDisplay(message).detail" class="message-error-detail">
                          {{ getAssistantErrorDisplay(message).detail }}
                        </div>
                        <div v-if="getEnvironmentCandidates(message).length" class="environment-candidate-list">
                          <button
                            v-for="candidate in getEnvironmentCandidates(message)"
                            :key="candidate.name"
                            type="button"
                            class="environment-candidate-btn"
                            :disabled="loading.send || loading.poll"
                            @click="chooseEnvironmentCandidate(message, index, candidate)"
                          >
                            <strong>{{ candidate.name }}</strong>
                            <span v-if="candidate.aliases?.length">{{ candidate.aliases.slice(0, 3).join(' / ') }}</span>
                          </button>
                        </div>
                        <div v-if="canViewConfig && getAssistantErrorDisplay(message).actionLabel" class="message-error-actions">
                          <el-button size="small" text @click="openAIOpsConfig">
                            {{ getAssistantErrorDisplay(message).actionLabel }}
                          </el-button>
                        </div>
                      </div>
                      <div v-else-if="message.role === 'assistant'" class="message-content assistant">
                        <template v-for="(block, blockIndex) in parseAssistantContent(getAssistantMainContent(message))" :key="`${message.localKey || message.id || index}-${blockIndex}`">
                          <div v-if="block.type === 'heading'" class="rich-heading">
                            <template v-for="(token, tokenIndex) in parseInlineMarkdown(block.text)" :key="`${blockIndex}-heading-${tokenIndex}`">
                              <strong v-if="token.type === 'strong'">{{ token.text }}</strong>
                              <em v-else-if="token.type === 'em'">{{ token.text }}</em>
                              <code v-else-if="token.type === 'code'" class="rich-inline-code">{{ token.text }}</code>
                              <a v-else-if="token.type === 'link'" :href="token.href" target="_blank" rel="noreferrer" class="rich-inline-link">{{ token.text }}</a>
                              <span v-else>{{ token.text }}</span>
                            </template>
                          </div>
                          <div v-else-if="block.type === 'paragraph'" class="rich-paragraph">
                            <template v-for="(token, tokenIndex) in parseInlineMarkdown(block.text)" :key="`${blockIndex}-paragraph-${tokenIndex}`">
                              <strong v-if="token.type === 'strong'">{{ token.text }}</strong>
                              <em v-else-if="token.type === 'em'">{{ token.text }}</em>
                              <code v-else-if="token.type === 'code'" class="rich-inline-code">{{ token.text }}</code>
                              <a v-else-if="token.type === 'link'" :href="token.href" target="_blank" rel="noreferrer" class="rich-inline-link">{{ token.text }}</a>
                              <span v-else>{{ token.text }}</span>
                            </template>
                          </div>
                          <ul v-else-if="block.type === 'list'" class="rich-list">
                            <li v-for="(item, itemIndex) in block.items" :key="`${blockIndex}-${itemIndex}`" class="rich-list-item">
                              <div class="rich-list-title">
                                <template v-for="(token, tokenIndex) in parseInlineMarkdown(item.text)" :key="`${blockIndex}-${itemIndex}-title-${tokenIndex}`">
                                  <strong v-if="token.type === 'strong'">{{ token.text }}</strong>
                                  <em v-else-if="token.type === 'em'">{{ token.text }}</em>
                                  <code v-else-if="token.type === 'code'" class="rich-inline-code">{{ token.text }}</code>
                                  <a v-else-if="token.type === 'link'" :href="token.href" target="_blank" rel="noreferrer" class="rich-inline-link">{{ token.text }}</a>
                                  <span v-else>{{ token.text }}</span>
                                </template>
                              </div>
                              <ul v-if="item.children?.length" class="rich-sublist">
                                <li v-for="(child, childIndex) in item.children" :key="`${blockIndex}-${itemIndex}-${childIndex}`">
                                  <template v-for="(token, tokenIndex) in parseInlineMarkdown(child)" :key="`${blockIndex}-${itemIndex}-${childIndex}-${tokenIndex}`">
                                    <strong v-if="token.type === 'strong'">{{ token.text }}</strong>
                                    <em v-else-if="token.type === 'em'">{{ token.text }}</em>
                                    <code v-else-if="token.type === 'code'" class="rich-inline-code">{{ token.text }}</code>
                                    <a v-else-if="token.type === 'link'" :href="token.href" target="_blank" rel="noreferrer" class="rich-inline-link">{{ token.text }}</a>
                                    <span v-else>{{ token.text }}</span>
                                  </template>
                                </li>
                              </ul>
                            </li>
                          </ul>
                          <pre v-else-if="block.type === 'code'" class="rich-code">{{ block.text }}</pre>
                        </template>
                      </div>
                      <div v-else class="message-content user-content">{{ message.content }}</div>

                      <div v-if="message.role === 'assistant' && getMessageBlocks(message).length" class="response-block-list">
                        <div
                          v-for="(responseBlock, responseBlockIndex) in getMessageBlocks(message)"
                          :key="`${message.id || message.localKey}-block-${responseBlock._key || responseBlockIndex}`"
                          class="response-block-card"
                          :class="[
                            `type-${responseBlock.type}`,
                            { 'is-collapsed': !isResponseBlockExpanded(message, responseBlock, responseBlockIndex) },
                          ]"
                        >
                          <div class="response-block-head">
                            <div class="response-block-headline">
                              <div class="response-block-title">{{ responseBlock.title }}</div>
                              <div v-if="responseBlock.summary" class="response-block-summary">{{ responseBlock.summary }}</div>
                            </div>
                            <div class="response-block-head-actions">
                              <span class="response-block-badge">{{ getBlockTypeLabel(responseBlock.type) }}</span>
                              <button type="button" class="response-block-toggle" @click="toggleResponseBlockExpanded(message, responseBlock, responseBlockIndex)">
                                {{ isResponseBlockExpanded(message, responseBlock, responseBlockIndex) ? '收起' : '展开' }}
                              </button>
                            </div>
                          </div>

                          <div v-show="isResponseBlockExpanded(message, responseBlock, responseBlockIndex)" class="response-block-content">
                            <div v-if="responseBlock.type === 'approval_form'" class="response-block-approval">
                              <div v-if="getBlockMetrics(responseBlock).length" class="response-block-metric-grid">
                                <div v-for="metric in getBlockMetrics(responseBlock)" :key="`${responseBlock._key}-metric-${metric.label}`" class="response-block-metric">
                                  <span>{{ metric.label }}</span>
                                  <strong>{{ metric.value }}</strong>
                                </div>
                              </div>
                              <div v-if="getPendingActionScriptContent(message.pending_action)" class="response-block-command">
                                {{ getPendingActionScriptContent(message.pending_action) }}
                              </div>
                            </div>

                            <div v-else-if="responseBlock.type === 'context_form'" class="response-block-context-form">
                              <div v-if="getBlockMetrics(responseBlock).length" class="response-block-metric-grid">
                                <div v-for="metric in getBlockMetrics(responseBlock)" :key="`${responseBlock._key}-metric-${metric.label}`" class="response-block-metric">
                                  <span>{{ metric.label }}</span>
                                  <strong>{{ metric.value }}</strong>
                                </div>
                              </div>
                              <div v-if="getBlockFields(responseBlock).length" class="response-block-field-list">
                                <div v-for="field in getBlockFields(responseBlock)" :key="`${responseBlock._key}-field-${field.name || field.label}`" class="response-block-field">
                                  <span>{{ field.label || field.name }}</span>
                                  <strong>{{ field.value || field.placeholder || '待补充' }}</strong>
                                </div>
                              </div>
                            </div>

                            <div v-else-if="responseBlock.type === 'tool_trace'" class="response-block-trace">
                              <div
                                v-for="item in getBlockItems(responseBlock)"
                                :key="`${responseBlock._key}-trace-${getBlockItemText(item)}`"
                                class="response-block-trace-item"
                                :class="getBlockItemStatus(item)"
                              >
                                <span class="response-block-trace-dot" :class="getBlockItemStatus(item)" />
                                <div class="response-block-trace-body">
                                  <div class="response-block-trace-name">{{ getBlockItemText(item) }}</div>
                                  <div class="response-block-trace-detail">{{ getBlockItemDetail(item) }}</div>
                                </div>
                              </div>
                            </div>

                            <div v-else-if="responseBlock.type === 'query_suggestion'" class="response-block-chip-list">
                              <button
                                v-for="item in getBlockItems(responseBlock)"
                                :key="`${responseBlock._key}-suggest-${getBlockItemText(item)}`"
                                type="button"
                                class="response-block-chip"
                                @click="reuseMessage(getBlockItemText(item))"
                              >
                                {{ getBlockItemText(item) }}
                              </button>
                            </div>

                            <div v-else-if="getBlockItems(responseBlock).length" class="response-block-item-list">
                              <div
                                v-for="item in getBlockItems(responseBlock)"
                                :key="`${responseBlock._key}-item-${getBlockItemText(item)}`"
                                class="response-block-item"
                              >
                                <span class="response-block-item-dot" />
                                <div class="response-block-item-body">
                                  <div class="response-block-item-text">{{ getBlockItemText(item) }}</div>
                                  <div v-if="getBlockItemDetail(item)" class="response-block-item-detail">{{ getBlockItemDetail(item) }}</div>
                                </div>
                              </div>
                            </div>

                            <div v-if="getBlockActions(responseBlock, message).length" class="response-block-actions">
                              <el-button
                                v-for="action in getBlockActions(responseBlock, message)"
                                :key="`${responseBlock._key}-action-${action.type || action.label}`"
                                size="small"
                                text
                                class="response-block-action-btn"
                                @click="handleBlockAction(responseBlock, action, message)"
                              >
                                <el-icon><component :is="getBlockActionIcon(action.type)" /></el-icon>
                                <span>{{ action.label || '操作' }}</span>
                              </el-button>
                            </div>
                          </div>
                        </div>
                      </div>

                      <div v-if="getAssistantFollowupLine(message)" class="assistant-followup-line">
                        {{ getAssistantFollowupLine(message) }}
                      </div>

                      <div v-if="getDisplayCitations(message).length" class="citation-row">
                        <button
                          v-for="citation in getDisplayCitations(message)"
                          :key="`${message.id || message.localKey}-${citation.displayTitle}-${citation.path || ''}`"
                          type="button"
                          class="citation-chip"
                          @click="jumpToCitation(citation)"
                        >
                          {{ citation.displayTitle }}
                        </button>
                      </div>

                      <div v-if="message.pending_action && !hasApprovalBlock(message)" class="pending-action-card">
                        <div class="pending-title-row">
                          <div class="pending-title">{{ message.pending_action.title }}</div>
                          <span class="pending-risk" :class="message.pending_action.risk_level">{{ message.pending_action.risk_level_display }}</span>
                        </div>
                        <div class="pending-meta">状态：{{ message.pending_action.status_display }}</div>
                        <div v-if="message.pending_action.status === 'pending'" class="pending-hint">
                          确认后将载入任务中心草稿，可编辑后再执行
                        </div>
                        <div v-if="message.pending_action.action_payload" class="pending-detail-grid">
                          <div class="pending-detail-item">
                            <span>{{ getActionTargetMetric(message.pending_action.action_payload).label }}</span>
                            <strong>{{ getActionTargetMetric(message.pending_action.action_payload).value }}</strong>
                          </div>
                          <div class="pending-detail-item">
                            <span>执行方式</span>
                            <strong>{{ message.pending_action.action_payload.execution_mode || '--' }}</strong>
                          </div>
                          <div class="pending-detail-item">
                            <span>执行策略</span>
                            <strong>{{ message.pending_action.action_payload.execution_strategy || '--' }}</strong>
                          </div>
                          <div class="pending-detail-item">
                            <span>超时</span>
                            <strong>{{ message.pending_action.action_payload.timeout_seconds || '--' }}s</strong>
                          </div>
                        </div>
                        <div
                          v-if="getPendingActionScriptContent(message.pending_action)"
                          class="pending-command"
                        >
                          {{ getPendingActionScriptContent(message.pending_action) }}
                        </div>
                        <div v-if="message.pending_action.status === 'pending'" class="pending-actions">
                          <el-button size="small" type="primary" @click="handleConfirmAction(message.pending_action)">{{ getPendingActionConfirmLabel(message.pending_action) }}</el-button>
                          <el-button size="small" @click="handleCancelAction(message.pending_action)">取消</el-button>
                        </div>
                        <div v-else-if="message.pending_action.result_payload?.draft_ready" class="pending-result">
                          <span>任务草稿已准备就绪</span>
                          <el-button size="small" text @click="handleConfirmAction(message.pending_action)">再次载入</el-button>
                          <el-button size="small" text @click="openTaskCenter">前往任务中心</el-button>
                        </div>
                        <div v-else-if="message.pending_action.result_payload?.task_id" class="pending-result">
                          <span>已创建任务 #{{ message.pending_action.result_payload.task_id }}</span>
                          <el-button size="small" text @click="openTaskCenter">查看任务中心</el-button>
                        </div>
                      </div>

                      <div v-else-if="message.metadata?.action_execution_disabled && !hasApprovalBlock(message)" class="message-state-card">
                        管理员已关闭机器人动作执行，当前只保留分析和任务草稿能力。
                      </div>


                    </div>
                  </div>
                </div>
              </div>

              <div class="aiops-composer">
                <el-input
                  ref="composerRef"
                  v-model="composer"
                  type="textarea"
                  :rows="2"
                  resize="none"
                  :maxlength="2000"
                  show-word-limit
                  placeholder="输入你的问题，Enter 发送，Shift + Enter 换行，Esc 收起"
                  @keydown="handleComposerKeydown"
                />
                <div class="composer-actions">
                  <div class="composer-meta">
                    <span class="composer-tip">Enter 发送，Shift + Enter 换行</span>
                    <span v-if="effectiveAnalysisOnly" class="composer-tip">当前为只分析模式</span>
                    <span v-if="composer.trim()" class="composer-tip">草稿已自动保存</span>
                    <span v-if="loading.poll" class="composer-tip">正在流式返回结果</span>
                  </div>
                  <div class="composer-action-group">
                    <el-button class="aiops-toolbar-btn" :disabled="!composer.trim()" @click="clearDraft">
                      <el-icon><Delete /></el-icon>
                      <span>清空</span>
                    </el-button>
                    <el-button type="primary" class="aiops-send-btn" :loading="loading.send || loading.poll" :disabled="!composer.trim() || loading.poll" @click="handleSend">
                      <el-icon><Promotion /></el-icon>
                      <span>发送</span>
                    </el-button>
                  </div>
                </div>
              </div>
            </section>
          </div>

          <transition name="aiops-sheet">
            <div v-if="mobileSessionVisible" class="mobile-session-sheet">
              <div class="mobile-session-head">
                <div class="session-head-title">
                  <span class="session-list-title">会话历史</span>
                  <el-button size="small" class="aiops-toolbar-btn" @click="handleCreateSession">
                    <el-icon><Plus /></el-icon>
                    <span>新建</span>
                  </el-button>
                </div>
                <el-button size="small" class="aiops-toolbar-btn" @click="mobileSessionVisible = false">
                  <el-icon><Fold /></el-icon>
                  <span>关闭</span>
                </el-button>
              </div>
              <div class="mobile-session-body">
                <div
                  v-for="session in sessions"
                  :key="`mobile-${session.id}`"
                  class="aiops-session-item"
                  :class="{ active: currentSessionId === session.id }"
                >
                  <button
                    type="button"
                    class="session-select-btn"
                    @click="selectSession(session.id)"
                  >
                    <el-tooltip
                      :disabled="!shouldShowSessionTooltip(session.title)"
                      :content="session.title || '新会话'"
                      effect="light"
                      placement="top"
                      :show-after="180"
                      popper-class="aiops-session-tooltip"
                    >
                      <span class="session-title">{{ session.title || '新会话' }}</span>
                    </el-tooltip>
                  </button>
                  <el-button
                    class="session-delete-btn mobile"
                    circle
                    text
                    :disabled="loading.deleteSession === session.id"
                    @click.stop="handleDeleteSession(session)"
                  >
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
                <div v-if="!sessions.length" class="session-empty">暂无历史会话</div>
              </div>
            </div>
          </transition>
        </div>
      </div>
    </transition>

    <button
      v-if="!embedded"
      type="button"
      ref="fabButtonRef"
      class="aiops-fab"
      :class="{ dragging: fabDragging }"
      @pointerdown="handleFabPointerDown"
      @click="toggleVisible"
    >
      <span class="aiops-fab-ring"></span>
      <span class="aiops-fab-core">
        <img :src="botAvatar" alt="AIOps bot" class="aiops-fab-avatar" />
      </span>
      <span class="aiops-fab-label">
        <strong>AIOps</strong>
        <small>智能助手</small>
      </span>
      <span class="aiops-fab-dot"></span>
    </button>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CircleCheck, CopyDocument, Delete, Fold, Plus, Promotion, TopRight } from '@element-plus/icons-vue'
import {
  cancelAIOpsAction,
  confirmAIOpsAction,
  createAIOpsSession,
  deleteAIOpsSession,
  getAIOpsBootstrap,
  getAIOpsMessages,
  getAIOpsSessions,
  sendAIOpsMessageAsync,
} from '@/api/modules/aiops'
import botAvatar from '@/assets/aiops-bot.svg'
import { useAuthStore } from '@/stores/auth'

const props = defineProps({
  embedded: {
    type: Boolean,
    default: false,
  },
})

const STORAGE_SESSION_KEY = 'sxdevops_aiops_current_session'
const STORAGE_VISIBLE_KEY = 'sxdevops_aiops_visible'
const STORAGE_ANALYSIS_KEY = 'sxdevops_aiops_analysis_only'
const STORAGE_DRAFT_PREFIX = 'sxdevops_aiops_draft_'
const AIOPS_SESSION_REQUEST_CONFIG = { skipErrorMessage: true }
const AIOPS_SESSION_MISSING_MESSAGE = '会话不存在或已被删除，请刷新会话列表后重新选择会话，或新建会话后再提问。'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const embedded = computed(() => props.embedded)
const visible = ref(props.embedded || localStorage.getItem(STORAGE_VISIBLE_KEY) === '1')
const analysisOnly = ref(localStorage.getItem(STORAGE_ANALYSIS_KEY) === '1')
const bootstrap = ref({ permissions: {}, suggested_questions: [], runtime: {} })
const sessions = ref([])
const messages = ref([])
const composer = ref('')
const currentSessionId = ref(Number(localStorage.getItem(STORAGE_SESSION_KEY) || '') || null)
const loading = ref({ bootstrap: false, sessions: false, messages: false, send: false, poll: false, deleteSession: null })
const pendingAssistantMessage = ref(null)
const messageListRef = ref(null)
const composerRef = ref(null)
const mobileSessionVisible = ref(false)
const isMobile = ref(typeof window !== 'undefined' ? window.innerWidth <= 920 : false)
const fabPosition = ref(null)
const fabDragging = ref(false)
const fabButtonRef = ref(null)
const fabPointerState = {
  pointerId: null,
  startX: 0,
  startY: 0,
  originLeft: 0,
  originTop: 0,
}
let ignoreNextFabClick = false
let pollingTimer = null
let pollingSessionId = null
let pollingMessageId = null
let pollingFinalizeAttempts = 0
const processExpandedState = ref({})
const processStatusState = ref({})
const responseBlockExpandedState = ref({})
const FINAL_POLL_MAX_ATTEMPTS = 4
const FINAL_POLL_STABLE_ROUNDS = 2

const available = computed(() => bootstrap.value.enabled && authStore.hasPermission('aiops.chat.view'))
const renderMessages = computed(() => pendingAssistantMessage.value ? [...messages.value, pendingAssistantMessage.value] : messages.value)
const currentSession = computed(() => sessions.value.find(item => item.id === currentSessionId.value) || null)
const actionExecutionAllowed = computed(() => bootstrap.value.runtime?.allow_action_execution !== false)
const forcedAnalysisOnly = computed(() => !actionExecutionAllowed.value)
const effectiveAnalysisOnly = computed(() => forcedAnalysisOnly.value || analysisOnly.value)
const analysisSwitchValue = computed({
  get: () => effectiveAnalysisOnly.value,
  set: value => {
    if (!forcedAnalysisOnly.value) {
      analysisOnly.value = value
    }
  },
})
const analysisHintText = computed(() => {
  if (forcedAnalysisOnly.value) return '平台已关闭待执行任务生成'
  return effectiveAnalysisOnly.value ? '本轮会强制只分析，不生成待执行任务' : '具备权限时可生成待执行动作'
})
const currentEnvironmentName = computed(() => {
  const value = currentSession.value?.context?.current_environment
  if (!value) return ''
  return typeof value === 'string' ? value : (value.name || '')
})
const fabStyle = computed(() => {
  if (!fabPosition.value || visible.value) return null
  return {
    left: `${fabPosition.value.left}px`,
    top: `${fabPosition.value.top}px`,
    right: 'auto',
    bottom: 'auto',
  }
})
const runtimeLabel = computed(() => {
  if (!bootstrap.value.runtime?.allow_action_execution) return '仅分析/草稿'
  return '可生成待执行任务'
})
const canViewConfig = computed(() => authStore.hasPermission('aiops.config.view'))

const ASSISTANT_ERROR_DISPLAY = {
  provider_unavailable: {
    title: '未配置可用模型',
    description: '当前智能助手没有可用模型，暂时无法继续问答。“智能助手体验版”只是预置模板，需要填写真实 Base URL 和 API Key。',
    actionLabel: '前往模型配置',
    tag: '模型配置',
  },
  llm_api_error: {
    title: 'LLM 接口调用失败',
    description: '模型服务已进入调用流程，但接口没有返回可用结果。请检查模型服务地址、模型名、API Key、网络连通性或服务端日志。',
    actionLabel: '检查模型配置',
    tag: 'LLM 接口',
  },
  tool_unavailable: {
    title: '未启用可用工具',
    description: '当前智能助手没有可调用的 MCP 工具，无法从平台数据中取证回答。请至少启用一个可用工具。',
    actionLabel: '前往 MCP 配置',
    tag: '工具配置',
  },
  no_tool_called: {
    title: '模型未发起工具调用',
    description: '本次问答已进入模型，但模型没有调用任何工具，因此平台无法基于真实数据完成回答。',
    actionLabel: '检查模型配置',
    tag: 'Tool Calling',
  },
  invalid_model_response: {
    title: '模型返回格式异常',
    description: '当前模型返回结果无法被平台正确解析，请检查模型兼容性，或更换支持 Tool Calling 的模型。',
    actionLabel: '检查模型配置',
    tag: '模型兼容性',
  },
  runtime_error: {
    title: '调用模型或工具时失败',
    description: '本次问答执行过程中发生异常，请稍后重试；如果持续失败，请检查模型与 MCP 的接入配置。',
    actionLabel: '查看智能体配置',
    tag: '运行异常',
  },
  environment_required: {
    title: '必须先指定环境',
    description: 'AIOps 分析需要先确认知识图谱环境。请在问题中带上环境名称，或从候选环境中选择后继续。',
    actionLabel: '',
    tag: '环境前置',
  },
  environment_ambiguous: {
    title: '需要确认唯一环境',
    description: '你的问题命中了多个知识图谱环境，请明确使用哪个环境后继续分析。',
    actionLabel: '',
    tag: '环境前置',
  },
  default: {
    title: '本次问答未完成',
    description: '智能助手暂时没能完成这次回答，请稍后重试，或检查模型与工具配置。',
    actionLabel: '查看智能体配置',
    tag: '运行状态',
  },
}

const DEMO_CHAT_DISABLED_MESSAGE = '演示账号问答权限已临时关闭，如需体验请联系作者：592095766@qq.com'

function normalizeText(value) {
  return String(value || '').replace(/\r\n/g, '\n')
}

function firstTextValue(source = {}, keys = []) {
  for (const key of keys) {
    const value = source?.[key]
    if (Array.isArray(value)) {
      const first = value.find(item => String(item || '').trim())
      if (first) return String(first).trim()
    } else if (value != null && String(value).trim()) {
      return String(value).trim()
    }
  }
  return ''
}

function routePageCode(path = '') {
  if (path.startsWith('/alerts')) return 'alerts'
  if (path.startsWith('/logs/query')) return 'logs.query'
  if (path.startsWith('/containers/k8s')) return 'containers.k8s'
  if (path.startsWith('/containers/docker')) return 'containers.docker'
    if (path.startsWith('/observability/tracing')) return 'observability.tracing'
  if (path.startsWith('/observability/metrics')) return 'observability.metrics'
  if (path.startsWith('/observability/grafana')) return 'observability.grafana'
  if (path.startsWith('/events')) return 'events'
  if (path.startsWith('/workorders/releases')) return 'deployments'
  if (path.startsWith('/tasks/resources')) return 'tasks.resources'
  if (path.startsWith('/tasks/workbench')) return 'tasks.workbench'
  if (path.startsWith('/aiops')) return 'aiops'
  return path.replace(/^\//, '').replace(/\//g, '.') || 'dashboard'
}

function buildPageSuggestedQuestions(page, hints = {}) {
  const env = hints.environment || '目标环境'
  const service = hints.service || '目标服务'
  const cluster = hints.cluster || '当前集群'
  if (page === 'alerts') {
    return [`分析${env}最新告警的可能原因`, `查看${env}当前未确认严重告警`]
  }
  if (page === 'logs.query') {
    return [`查询${env}${service}最近 30 分钟 ERROR 日志`, `分析${service}日志里的异常模式`]
  }
  if (page === 'containers.k8s') {
    return [`分析${cluster}异常工作负载`, `查看${cluster}当前异常 Pod`]
  }
  if (page.startsWith('observability')) {
    return [`分析${env}${service}最近一小时服务健康`, `查看${service}错误率和延迟是否异常`]
  }
  if (page === 'events' || page === 'deployments') {
    return [`分析${env}最近变更和告警是否相关`, `查看${env}今天关键事件时间线`]
  }
  if (page.startsWith('tasks')) {
    return [`帮我生成${env}服务器巡检任务`, `根据当前资源范围生成任务草稿`]
  }
  return []
}

function buildPageContext() {
  const query = { ...(route.query || {}) }
  const params = { ...(route.params || {}) }
  const merged = { ...query, ...params }
  const hints = {
    environment: firstTextValue(merged, ['environment', 'env', 'env_name', 'knowledge_environment']),
    service: firstTextValue(merged, ['service', 'service_name', 'app', 'application', 'system', 'workload']),
    cluster: firstTextValue(merged, ['cluster', 'cluster_name', 'k8s_cluster']),
    namespace: firstTextValue(merged, ['namespace', 'ns']),
    alert_id: firstTextValue(merged, ['alert_id', 'alertId', 'id']),
    datasource_id: firstTextValue(merged, ['datasource_id', 'datasourceId', 'ds_id']),
    datasource_type: firstTextValue(merged, ['datasource_type', 'datasourceType', 'ds_type']),
  }
  Object.keys(hints).forEach((key) => {
    if (!hints[key]) delete hints[key]
  })
  const page = routePageCode(route.path)
  const title = route.meta?.title || page
  return {
    page,
    title,
    route: route.path,
    params,
    query,
    hints,
    suggested_questions: buildPageSuggestedQuestions(page, hints),
  }
}

function normalizeLinkHref(value) {
  const href = String(value || '').trim()
  if (!href) return ''
  if (/^(https?:|mailto:)/i.test(href)) return href
  return ''
}

function parseInlineMarkdown(text) {
  const source = String(text || '')
  if (!source) return [{ type: 'text', text: '' }]

  const tokens = []
  const pattern = /(`([^`\n]+)`)|(\[([^\]]+)\]\(([^)]+)\))|(\*\*([^*\n]+)\*\*)|(\*([^*\n]+)\*)/g
  let lastIndex = 0
  let match = pattern.exec(source)

  while (match) {
    if (match.index > lastIndex) {
      tokens.push({ type: 'text', text: source.slice(lastIndex, match.index) })
    }
    if (match[2]) {
      tokens.push({ type: 'code', text: match[2] })
    } else if (match[4] && match[5]) {
      const href = normalizeLinkHref(match[5])
      if (href) {
        tokens.push({ type: 'link', text: match[4], href })
      } else {
        tokens.push({ type: 'text', text: match[4] })
      }
    } else if (match[7]) {
      tokens.push({ type: 'strong', text: match[7] })
    } else if (match[9]) {
      tokens.push({ type: 'em', text: match[9] })
    }
    lastIndex = pattern.lastIndex
    match = pattern.exec(source)
  }

  if (lastIndex < source.length) {
    tokens.push({ type: 'text', text: source.slice(lastIndex) })
  }

  return tokens.length ? tokens : [{ type: 'text', text: source }]
}

function isAssistantErrorMessage(message) {
  if (message?.role !== 'assistant') return false
  return message?.message_type === 'error' || Boolean(message?.metadata?.error_code)
}

function getAssistantErrorDisplay(message) {
  const code = message?.metadata?.error_code
  const errorDetail = String(message?.metadata?.error_detail || '').trim()
  const preset = ASSISTANT_ERROR_DISPLAY[code] || ASSISTANT_ERROR_DISPLAY.default
  return {
    ...preset,
    detail: errorDetail || '',
  }
}

function getEnvironmentCandidates(message) {
  const candidates = message?.metadata?.environment_candidates
  if (!Array.isArray(candidates)) return []
  const seen = new Set()
  return candidates
    .map(item => ({
      name: String(item?.name || '').trim(),
      aliases: Array.isArray(item?.aliases) ? item.aliases.filter(Boolean) : [],
    }))
    .filter((item) => {
      if (!item.name || seen.has(item.name)) return false
      seen.add(item.name)
      return true
    })
}

const RESPONSE_BLOCK_TYPE_LABELS = {
  context_summary: '上下文',
  context_form: '预检',
  incident_card: '摘要',
  evidence_timeline: '证据',
  query_suggestion: '建议',
  chart_query: '图表',
  alert_rule_draft: '草稿',
  dashboard_draft: '草稿',
  change_candidate: '变更',
  rollback_plan: '回滚',
  k8s_action: 'K8s',
  self_heal_recommendation: '自愈',
  approval_form: '待确认',
  tool_trace: '追踪',
  risk_notice: '风险',
}

function normalizeResponseBlockItems(items) {
  if (!Array.isArray(items)) return []
  return items
    .map((item) => {
      if (item == null) return null
      if (typeof item === 'string') {
        const text = String(item || '').trim()
        return text ? { text } : null
      }
      if (typeof item !== 'object') return null
      const text = String(item.text || item.title || item.label || item.name || item.value || '').trim()
      if (!text) return null
      return {
        ...item,
        text,
      }
    })
    .filter(Boolean)
}

function normalizeResponseBlockFields(fields) {
  if (!Array.isArray(fields)) return []
  return fields
    .map((field) => {
      if (!field || typeof field !== 'object') return null
      const name = String(field.name || '').trim()
      const label = String(field.label || name || '').trim()
      if (!name && !label) return null
      return {
        ...field,
        name,
        label,
        value: String(field.value || '').trim(),
        placeholder: String(field.placeholder || '').trim(),
      }
    })
    .filter(Boolean)
}

function normalizeShortcutTitle(value) {
  let title = String(value || '').trim()
  title = title.replace(/^\s*(?:[-*+]\s+|\d+\.\s+)?/, '')
  title = title.replace(/^可继续查看[:：]\s*/, '')
  title = title.replace(/^\[([^\]]+)\]\((?:\/|https?:\/\/)[^)]+\)$/, '$1')
  title = title.replace(/^([^:：]+)\s*[:：]\s*`?(?:\/|https?:\/\/).*`?$/, '$1')
  title = title.replace(/\s*[（(]\s*(?:\/|https?:\/\/)[^)）]+\s*[)）]$/, '')
  title = title.trim().replace(/[。；;、，,\s]+$/g, '')
  if (/链路追踪|调用链|Trace|Tracing|Tempo|OpenTelemetry/i.test(title)) {
    return '链路追踪'
  }
  return title
}

function splitFollowupTitles(value) {
  const source = String(value || '').trim().replace(/^可继续查看[:：]\s*/, '')
  return source
    .split(/[、，,；;]\s*/)
    .map(normalizeShortcutTitle)
    .filter(Boolean)
}

function getAssistantFollowupTitles(message) {
  const lines = normalizeText(message?.content || '').split('\n')
  const titles = []
  const seen = new Set()
  for (let index = 0; index < lines.length; index += 1) {
    const trimmed = lines[index].trim()
    if (!/^可继续查看[:：]/.test(trimmed)) continue
    const inlineValue = trimmed.replace(/^可继续查看[:：]\s*/, '')
    const candidates = inlineValue ? [inlineValue] : []
    for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
      const nextLine = lines[cursor].trim()
      if (!nextLine) break
      if (/^(结论|依据|建议|建议操作|关键点|执行概要|下一步)[:：]/.test(nextLine)) break
      if (/^(?:[-*+]\s+|\d+\.\s+)/.test(nextLine)) {
        candidates.push(nextLine)
        continue
      }
      break
    }
    for (const title of candidates.flatMap(splitFollowupTitles)) {
      if (seen.has(title)) continue
      seen.add(title)
      titles.push(title)
    }
  }
  return titles
}

function getAssistantFollowupLine(message) {
  const titles = getAssistantFollowupTitles(message)
  return titles.length ? `可继续查看：${titles.join('、')}。` : ''
}

function isAssistantSectionHeading(value) {
  return /^(结论|依据|建议|建议操作|关键点|执行概要|下一步)[:：]/.test(String(value || '').trim())
}

function getFollowupLineEndIndex(lines, startIndex) {
  let cursor = startIndex + 1
  while (cursor < lines.length) {
    const nextLine = String(lines[cursor] || '').trim()
    if (!nextLine) return cursor
    if (isAssistantSectionHeading(nextLine)) return cursor - 1
    if (/^(?:[-*+]\s+|\d+\.\s+)/.test(nextLine)) {
      cursor += 1
      continue
    }
    return cursor - 1
  }
  return lines.length - 1
}

function getAssistantMainContent(message) {
  const lines = normalizeText(message?.content || '').split('\n')
  const kept = []
  let index = 0
  while (index < lines.length) {
    const trimmed = lines[index].trim()
    if (/^可继续查看[:：]/.test(trimmed)) {
      index = getFollowupLineEndIndex(lines, index) + 1
      continue
    }
    kept.push(lines[index])
    index += 1
  }
  return kept.join('\n').trim()
}

function getDisplayCitations(message) {
  const seen = new Set()
  return (message?.citations || [])
    .map(citation => ({
      ...citation,
      displayTitle: normalizeShortcutTitle(citation?.title),
    }))
    .filter((citation) => {
      if (!citation.displayTitle) return false
      const key = `${citation.displayTitle}:${citation.path || ''}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

function isK8sActionPayload(payload) {
  return payload?.target_type === 'k8s' || String(payload?.task_type || '').startsWith('k8s_')
}

function getActionTargetMetric(payload) {
  const isK8s = isK8sActionPayload(payload)
  return {
    label: isK8s ? 'K8s 目标' : '目标主机',
    value: `${payload?.host_count || 0} ${isK8s ? '个' : '台'}`,
  }
}

function buildApprovalFormBlock(pendingAction) {
  const payload = pendingAction?.action_payload || {}
  const metrics = [
    getActionTargetMetric(payload),
    { label: '执行方式', value: payload.execution_mode || '--' },
    { label: '执行策略', value: payload.execution_strategy || '--' },
    { label: '超时', value: `${payload.timeout_seconds || '--'}s` },
  ]
  return {
    type: 'approval_form',
    title: pendingAction?.title || '待确认动作',
    summary: pendingAction?.status === 'pending'
      ? '确认后将载入任务中心草稿，可编辑后再执行。'
      : '动作已进入下一步处理。',
    status: pendingAction?.status || 'pending',
    status_display: pendingAction?.status_display || '待确认',
    risk_level: pendingAction?.risk_level || 'low',
    metrics,
    items: metrics.map(item => ({ text: `${item.label}：${item.value}`, ...item })),
    actions: [],
    _key: `pending-action-${pendingAction?.id || 'legacy'}`,
  }
}

function getPendingActionScriptContent(pendingAction) {
  const payload = pendingAction?.action_payload?.payload || {}
  return payload.command || payload.playbook_content || ''
}

function getMessageBlocks(message) {
  const rawBlocks = Array.isArray(message?.blocks)
    ? message.blocks
    : Array.isArray(message?.metadata?.response_blocks)
      ? message.metadata.response_blocks
      : []
  const blocks = rawBlocks
    .filter(Boolean)
    .map((block, index) => {
      const normalizedItems = normalizeResponseBlockItems(block?.items)
      const type = String(block?.type || 'incident_card')
      return {
        ...block,
        type,
        title: String(block?.title || RESPONSE_BLOCK_TYPE_LABELS[type] || '结构化信息').trim(),
        summary: String(block?.summary || normalizedItems[0]?.text || '').trim(),
        items: normalizedItems,
        actions: Array.isArray(block?.actions) ? block.actions.filter(Boolean) : [],
        metrics: Array.isArray(block?.metrics) ? block.metrics.filter(Boolean) : [],
        fields: normalizeResponseBlockFields(block?.fields),
        _key: String(block?.id || block?.key || `${type}-${index}`),
      }
    })

  if (message?.pending_action && !blocks.some(block => block.type === 'approval_form')) {
    blocks.push(buildApprovalFormBlock(message.pending_action))
  }

  return blocks
}

function hasApprovalBlock(message) {
  return getMessageBlocks(message).some(block => block.type === 'approval_form')
}

function getResponseBlockStateKey(message, block, index = 0) {
  const messageKey = String(message?.id || message?.localKey || '').trim()
  const blockKey = String(block?._key || block?.id || block?.key || `${block?.type || 'block'}-${index}`).trim()
  return messageKey && blockKey ? `${messageKey}:${blockKey}` : ''
}

function isResponseBlockExpanded(message, block, index = 0) {
  const key = getResponseBlockStateKey(message, block, index)
  if (!key) return false
  if (Object.prototype.hasOwnProperty.call(responseBlockExpandedState.value, key)) {
    return Boolean(responseBlockExpandedState.value[key])
  }
  return isResponseBlockDefaultExpanded(block, message)
}

function toggleResponseBlockExpanded(message, block, index = 0) {
  const key = getResponseBlockStateKey(message, block, index)
  if (!key) return
  responseBlockExpandedState.value = {
    ...responseBlockExpandedState.value,
    [key]: !isResponseBlockExpanded(message, block, index),
  }
}

function isResponseBlockDefaultExpanded(block, message) {
  const type = String(block?.type || '')
  return Boolean(
    type === 'approval_form'
    || type === 'alert_rule_draft'
    || type === 'dashboard_draft'
    || (message?.pending_action && type.includes('draft'))
  )
}

function syncResponseBlockState(list = renderMessages.value) {
  const nextExpanded = {}
  for (const message of list || []) {
    if (message?.role !== 'assistant') continue
    getMessageBlocks(message).forEach((block, index) => {
      const key = getResponseBlockStateKey(message, block, index)
      if (!key) return
      nextExpanded[key] = Object.prototype.hasOwnProperty.call(responseBlockExpandedState.value, key)
        ? Boolean(responseBlockExpandedState.value[key])
        : isResponseBlockDefaultExpanded(block, message)
    })
  }
  responseBlockExpandedState.value = nextExpanded
}

function getBlockTypeLabel(type) {
  return RESPONSE_BLOCK_TYPE_LABELS[String(type || '')] || '结构化信息'
}

function getBlockItemText(item) {
  return String(item?.text || item?.label || item?.title || item?.name || item?.value || '').trim()
}

function getBlockItemDetail(item) {
  return String(item?.detail || item?.description || item?.message || '').trim()
}

function getBlockItemStatus(item) {
  return String(item?.status || '').trim()
}

function getBlockCopyValue(block) {
  const lines = [String(block?.title || '').trim(), String(block?.summary || '').trim()]
  const itemLines = (block?.items || []).map(getBlockItemText).filter(Boolean)
  return [...lines.filter(Boolean), ...itemLines].join('\n')
}

function getBlockMetrics(block) {
  return Array.isArray(block?.metrics) ? block.metrics.filter(Boolean) : []
}

function getBlockFields(block) {
  return Array.isArray(block?.fields) ? block.fields.filter(Boolean) : []
}

function getBlockItems(block) {
  return Array.isArray(block?.items) ? block.items.filter(Boolean) : []
}

function getBlockActions(block, message) {
  const actions = Array.isArray(block?.actions) ? block.actions.filter(Boolean).map(action => ({ ...action })) : []
  if (block?.type === 'approval_form') {
    const actionTypes = new Set(actions.map(action => action.type).filter(Boolean))
    if (message?.pending_action?.result_payload?.draft_ready) {
      actions.forEach((action) => {
        if (action.type === 'confirm') action.label = '再次载入'
      })
    }
    if (message?.pending_action?.status === 'pending') {
      if (!actionTypes.has('confirm')) actions.unshift({ type: 'confirm', label: getPendingActionConfirmLabel(message.pending_action) })
      if (!actionTypes.has('cancel')) actions.push({ type: 'cancel', label: '取消' })
    } else if (message?.pending_action?.result_payload?.draft_ready) {
      if (!actionTypes.has('confirm')) actions.unshift({ type: 'confirm', label: '再次载入' })
      if (!actionTypes.has('open_task_center')) actions.push({ type: 'open_task_center', label: '前往任务中心' })
    } else if (message?.pending_action?.result_payload?.task_id) {
      if (!actionTypes.has('open_task_center')) actions.unshift({ type: 'open_task_center', label: '查看任务中心' })
    }
  }
  if (!actions.length && block?.summary) {
    actions.push({ type: 'copy', label: '复制内容', value: getBlockCopyValue(block) })
  }
  return actions
}

function getPendingActionConfirmLabel(pendingAction) {
  return pendingAction?.result_payload?.draft_ready ? '再次载入' : '确认载入'
}

function getBlockActionIcon(type) {
  if (type === 'copy') return CopyDocument
  if (type === 'open' || type === 'open_task_center') return TopRight
  if (type === 'reuse') return Promotion
  if (type === 'confirm') return CircleCheck
  if (type === 'cancel') return Delete
  return CopyDocument
}

async function handleBlockAction(block, action, message) {
  const type = String(action?.type || '').trim()
  if (type === 'copy') {
    await copyMessage(action?.value || getBlockCopyValue(block))
    return
  }
  if (type === 'reuse') {
    reuseMessage(action?.value || getBlockCopyValue(block))
    return
  }
  if (type === 'open' && action?.path) {
    router.push({ path: action.path, query: action.query || {} })
    closePanel()
    return
  }
  if (type === 'open_task_center') {
    openTaskCenter()
    return
  }
  if (type === 'confirm' && message?.pending_action) {
    await handleConfirmAction(message.pending_action)
    return
  }
  if (type === 'cancel' && message?.pending_action) {
    await handleCancelAction(message.pending_action)
  }
}

function formatDateTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function shouldShowSessionTooltip(title) {
  return String(title || '新会话').trim().length > 14
}

function formatProcessTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function formatProcessDuration(seconds) {
  const safeSeconds = Math.max(0, Math.round(Number(seconds) || 0))
  if (safeSeconds < 60) return `${safeSeconds} 秒`
  const minutes = Math.floor(safeSeconds / 60)
  const remainSeconds = safeSeconds % 60
  if (!remainSeconds) return `${minutes} 分钟`
  return `${minutes} 分 ${remainSeconds} 秒`
}

function getProcessingStatus(message) {
  return message?.metadata?.processing_status || ''
}

function isMessageProcessing(message) {
  return ['pending', 'running', 'streaming'].includes(getProcessingStatus(message))
}

function shouldShowProcessCard(message) {
  if (message?.role !== 'assistant') return false
  return Boolean(
    isMessageProcessing(message)
    || message?.metadata?.processing_text
    || message?.metadata?.processing_steps?.length
    || message?.metadata?.tool_events?.length
  )
}

function getProcessingStatusLabel(message) {
  const status = getProcessingStatus(message)
  if (status === 'pending') return '排队中'
  if (status === 'running') return '分析中'
  if (status === 'streaming') return '输出中'
  if (status === 'failed') return '失败'
  if (status === 'completed') return '已完成'
  return '处理中'
}

function getProcessTimeline(message) {
  const steps = message?.metadata?.processing_steps || []
  const toolEvents = message?.metadata?.tool_events || []
  const timestamps = [
    message?.created_at,
    ...steps.map(item => item?.timestamp),
    ...toolEvents.map(item => item?.timestamp),
  ].filter(Boolean).map(value => new Date(value).getTime()).filter(value => Number.isFinite(value))
  if (!timestamps.length) return 0
  const start = Math.min(...timestamps)
  const end = ['pending', 'running', 'streaming'].includes(getProcessingStatus(message))
    ? Date.now()
    : Math.max(...timestamps)
  return Math.max(1, Math.round((end - start) / 1000))
}

function getProcessSummary(message) {
  const durationText = `已思考 ${formatProcessDuration(getProcessTimeline(message))}`
  const toolEvents = message?.metadata?.tool_events || []
  const toolCount = new Set(toolEvents.map(item => item?.name).filter(Boolean)).size
  const stepCount = (message?.metadata?.processing_steps || []).length
  const parts = [durationText]
  if (toolCount) {
    parts.push(`调用 ${toolCount} 个工具`)
  } else if (stepCount) {
    parts.push(`${stepCount} 个步骤`)
  }
  if (getProcessingStatus(message) === 'failed') {
    parts.push('处理未完成')
  }
  return parts.join(' · ')
}

function getProcessMessageKey(message) {
  return String(message?.id || message?.localKey || '')
}

function isProcessExpanded(message) {
  const key = getProcessMessageKey(message)
  if (!key) return isMessageProcessing(message)
  if (Object.prototype.hasOwnProperty.call(processExpandedState.value, key)) {
    return processExpandedState.value[key]
  }
  return isMessageProcessing(message)
}

function toggleProcessExpanded(message) {
  const key = getProcessMessageKey(message)
  if (!key) return
  processExpandedState.value = {
    ...processExpandedState.value,
    [key]: !isProcessExpanded(message),
  }
}

function syncProcessCardState(list = renderMessages.value) {
  const nextExpanded = {}
  const nextStatus = {}
  for (const message of list || []) {
    if (!shouldShowProcessCard(message)) continue
    const key = getProcessMessageKey(message)
    if (!key) continue
    const status = getProcessingStatus(message) || 'completed'
    const previousStatus = processStatusState.value[key]
    if (Object.prototype.hasOwnProperty.call(processExpandedState.value, key)) {
      nextExpanded[key] = processExpandedState.value[key]
    } else {
      nextExpanded[key] = isMessageProcessing(message)
    }
    if (
      ['pending', 'running', 'streaming'].includes(previousStatus)
      && ['completed', 'failed'].includes(status)
    ) {
      nextExpanded[key] = false
    }
    nextStatus[key] = status
  }
  processExpandedState.value = nextExpanded
  processStatusState.value = nextStatus
}

function buildQuestionPayload(raw) {
  return raw.trim()
}

function getDraftStorageKey(sessionId = currentSessionId.value) {
  return `${STORAGE_DRAFT_PREFIX}${sessionId || 'default'}`
}

function persistDraft(sessionId = currentSessionId.value, value = composer.value) {
  localStorage.setItem(getDraftStorageKey(sessionId), value || '')
}

function loadDraft(sessionId = currentSessionId.value) {
  composer.value = localStorage.getItem(getDraftStorageKey(sessionId)) || ''
}

function focusComposer() {
  nextTick(() => {
    composerRef.value?.focus?.()
  })
}

function handleResize() {
  isMobile.value = window.innerWidth <= 920
  if (!isMobile.value) {
    mobileSessionVisible.value = false
  }
  if (fabPosition.value) {
    fabPosition.value = clampFabPosition(fabPosition.value.left, fabPosition.value.top)
  }
}

function getFabOffsets() {
  return isMobile.value ? { right: 12, bottom: 12 } : { right: 24, bottom: 24 }
}

function getFabRect() {
  const fabEl = fabButtonRef.value
  if (!fabEl) return { width: 132, height: 58 }
  const rect = fabEl.getBoundingClientRect()
  return { width: rect.width, height: rect.height }
}

function clampFabPosition(left, top) {
  const { width, height } = getFabRect()
  const minX = 8
  const minY = 8
  const maxX = Math.max(minX, window.innerWidth - width - 8)
  const maxY = Math.max(minY, window.innerHeight - height - 8)
  return {
    left: Math.min(Math.max(left, minX), maxX),
    top: Math.min(Math.max(top, minY), maxY),
  }
}

function resetFabPosition() {
  fabPosition.value = null
  fabDragging.value = false
}

function handleFabPointerMove(event) {
  if (fabPointerState.pointerId !== event.pointerId) return
  const deltaX = event.clientX - fabPointerState.startX
  const deltaY = event.clientY - fabPointerState.startY
  if (!fabDragging.value && Math.hypot(deltaX, deltaY) < 6) return
  fabDragging.value = true
  fabPosition.value = clampFabPosition(
    fabPointerState.originLeft + deltaX,
    fabPointerState.originTop + deltaY,
  )
}

function cleanupFabPointerListeners() {
  window.removeEventListener('pointermove', handleFabPointerMove)
  window.removeEventListener('pointerup', handleFabPointerUp)
  window.removeEventListener('pointercancel', handleFabPointerUp)
}

function handleFabPointerUp(event) {
  if (fabPointerState.pointerId !== event.pointerId) return
  if (fabDragging.value) {
    ignoreNextFabClick = true
  }
  fabPointerState.pointerId = null
  cleanupFabPointerListeners()
}

function handleFabPointerDown(event) {
  if (embedded.value) return
  if (visible.value) return
  const fabEl = event.currentTarget
  fabButtonRef.value = fabEl
  const rect = fabEl.getBoundingClientRect()
  fabPointerState.pointerId = event.pointerId
  fabPointerState.startX = event.clientX
  fabPointerState.startY = event.clientY
  fabPointerState.originLeft = fabPosition.value?.left ?? rect.left
  fabPointerState.originTop = fabPosition.value?.top ?? rect.top
  fabDragging.value = false
  window.addEventListener('pointermove', handleFabPointerMove)
  window.addEventListener('pointerup', handleFabPointerUp)
  window.addEventListener('pointercancel', handleFabPointerUp)
}

function parseAssistantContent(content) {
  const source = normalizeText(content).trim()
  if (!source) return [{ type: 'paragraph', text: '' }]

  const blocks = []
  const lines = source.split('\n')
  let paragraphLines = []
  let listItems = []
  let codeLines = []
  let inCode = false

  const pushParagraph = () => {
    if (!paragraphLines.length) return
    blocks.push({ type: 'paragraph', text: paragraphLines.join('\n') })
    paragraphLines = []
  }

  const pushList = () => {
    if (!listItems.length) return
    blocks.push({ type: 'list', items: listItems })
    listItems = []
  }

  const pushCode = () => {
    if (!codeLines.length) return
    blocks.push({ type: 'code', text: codeLines.join('\n') })
    codeLines = []
  }

  for (const line of lines) {
    const rawLine = line.replace(/\t/g, '  ')
    const trimmed = rawLine.trim()

    if (trimmed.startsWith('```')) {
      pushParagraph()
      pushList()
      if (inCode) {
        pushCode()
        inCode = false
      } else {
        inCode = true
      }
      continue
    }

    if (inCode) {
      codeLines.push(rawLine)
      continue
    }

    if (!trimmed) {
      pushParagraph()
      pushList()
      continue
    }

    if (/^\*\*.*\*\*$/.test(trimmed)) {
      pushParagraph()
      pushList()
      blocks.push({ type: 'heading', text: trimmed.replace(/^\*\*|\*\*$/g, '').trim() })
      continue
    }

    if (/^#{1,6}\s+/.test(trimmed)) {
      pushParagraph()
      pushList()
      blocks.push({ type: 'heading', text: trimmed.replace(/^#{1,6}\s+/, '').trim() })
      continue
    }

    if (/^\s{2,}\S/.test(rawLine) && listItems.length) {
      listItems[listItems.length - 1].children.push(trimmed)
      continue
    }

    if (/^(-|•)\s+/.test(trimmed) || /^\d+\.\s+/.test(trimmed)) {
      pushParagraph()
      listItems.push({
        text: trimmed.replace(/^(-|•)\s+/, '').replace(/^\d+\.\s+/, '').trim(),
        children: [],
      })
      continue
    }

    pushList()
    paragraphLines.push(trimmed)
  }

  pushParagraph()
  pushList()
  pushCode()
  return blocks.length ? blocks : [{ type: 'paragraph', text: source }]
}

function stopMessagePolling() {
  if (pollingTimer) {
    window.clearTimeout(pollingTimer)
    pollingTimer = null
  }
  pollingSessionId = null
  pollingMessageId = null
  pollingFinalizeAttempts = 0
  loading.value.poll = false
}

function findProcessingAssistant(list = messages.value) {
  return [...(list || [])].reverse().find(item => item.role === 'assistant' && isMessageProcessing(item)) || null
}

async function refreshSessionListOnly() {
  const response = await getAIOpsSessions()
  sessions.value = response.results || response || []
}

function isAIOpsSessionMissingError(error) {
  const status = error?.response?.status
  const requestUrl = String(error?.config?.url || '')
  const detail = error?.response?.data?.detail
  const message = typeof detail === 'string' ? detail : ''
  return status === 404
    && requestUrl.includes('/aiops/sessions/')
    && (message.includes('会话不存在') || message.includes('AIOpsChatSession'))
}

function clearCurrentSessionIfMatches(sessionId) {
  if (!sessionId || currentSessionId.value === sessionId) {
    stopMessagePolling()
    currentSessionId.value = null
    localStorage.removeItem(STORAGE_SESSION_KEY)
    messages.value = []
    loadDraft(null)
  }
}

async function handleMissingChatSession(sessionId) {
  clearCurrentSessionIfMatches(sessionId)
  try {
    await refreshSessionListOnly()
  } catch {
    // 保留本地清理结果，避免继续用失效会话发请求。
  }
  ElMessage.warning(AIOPS_SESSION_MISSING_MESSAGE)
}

async function applyLatestMessages(sessionId, latestMessages) {
  if (currentSessionId.value !== sessionId) return
  messages.value = latestMessages
  await nextTick()
  scrollToBottom(true)
}

function getMessageStableSignature(message) {
  if (!message) return 'missing'
  return JSON.stringify({
    status: getProcessingStatus(message),
    contentLength: normalizeText(message.content).length,
    citations: (message.citations || []).map(item => item?.title || ''),
    toolCalls: message.tool_calls || [],
    pendingActionId: message.pending_action?.id || null,
  })
}

function waitFor(ms) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

function resumeMessagePolling(sessionId, list = messages.value) {
  const target = findProcessingAssistant(list)
  if (!target?.id) {
    if (pollingSessionId === sessionId) {
      stopMessagePolling()
    }
    return
  }
  startMessagePolling(sessionId, target.id)
}

function startMessagePolling(sessionId, assistantMessageId) {
  if (!sessionId || !assistantMessageId) return
  if (pollingSessionId === sessionId && pollingMessageId === assistantMessageId && pollingTimer) return
  stopMessagePolling()
  pollingSessionId = sessionId
  pollingMessageId = assistantMessageId
  pollingFinalizeAttempts = 0
  loading.value.poll = true

  const finalizePoll = async () => {
    if (!pollingSessionId || pollingSessionId !== sessionId || pollingMessageId !== assistantMessageId) return
    let missingSessionHandled = false
    try {
      let stableRounds = 0
      let previousSignature = ''
      for (let attempt = 0; attempt < FINAL_POLL_MAX_ATTEMPTS; attempt += 1) {
        const latestMessages = await getAIOpsMessages(sessionId, AIOPS_SESSION_REQUEST_CONFIG)
        await applyLatestMessages(sessionId, latestMessages)
        const target = latestMessages.find(item => item.id === assistantMessageId)
        const status = getProcessingStatus(target)
        const signature = getMessageStableSignature(target)
        if ((!target || ['completed', 'failed'].includes(status)) && signature === previousSignature) {
          stableRounds += 1
        } else {
          stableRounds = 0
        }
        previousSignature = signature
        if ((!target || ['completed', 'failed'].includes(status)) && stableRounds >= FINAL_POLL_STABLE_ROUNDS - 1) {
          break
        }
        await waitFor(attempt === 0 ? 240 : 360)
      }
    } catch (error) {
      if (isAIOpsSessionMissingError(error)) {
        missingSessionHandled = true
        await handleMissingChatSession(sessionId)
        return
      }
      throw error
    } finally {
      stopMessagePolling()
      if (!missingSessionHandled) {
        await refreshSessionListOnly()
      }
    }
  }

  const poll = async () => {
    try {
      const latestMessages = await getAIOpsMessages(sessionId, AIOPS_SESSION_REQUEST_CONFIG)
      await applyLatestMessages(sessionId, latestMessages)
      const target = latestMessages.find(item => item.id === assistantMessageId)
      const status = getProcessingStatus(target)
      if (!target || ['completed', 'failed'].includes(status)) {
        if (pollingFinalizeAttempts < 1) {
          pollingFinalizeAttempts += 1
          pollingTimer = window.setTimeout(finalizePoll, 240)
          return
        }
        await finalizePoll()
        return
      }
      pollingTimer = window.setTimeout(poll, 1000)
    } catch (error) {
      if (isAIOpsSessionMissingError(error)) {
        await handleMissingChatSession(sessionId)
        return
      }
      if (pollingFinalizeAttempts < 1) {
        pollingFinalizeAttempts += 1
        pollingTimer = window.setTimeout(finalizePoll, 320)
        return
      }
      stopMessagePolling()
    }
  }

  pollingTimer = window.setTimeout(poll, 900)
}

async function fetchBootstrap() {
  loading.value.bootstrap = true
  try {
    bootstrap.value = await getAIOpsBootstrap()
  } finally {
    loading.value.bootstrap = false
  }
}

async function fetchSessions() {
  loading.value.sessions = true
  try {
    await refreshSessionListOnly()
    if (currentSessionId.value && sessions.value.some(item => item.id === currentSessionId.value)) {
      await selectSession(currentSessionId.value)
      return
    }
    if (currentSessionId.value) {
      clearCurrentSessionIfMatches(currentSessionId.value)
    }
    if (sessions.value.length) {
      await selectSession(sessions.value[0].id)
    } else {
      loadDraft(null)
    }
  } finally {
    loading.value.sessions = false
  }
}

async function selectSession(sessionId) {
  stopMessagePolling()
  currentSessionId.value = sessionId
  localStorage.setItem(STORAGE_SESSION_KEY, String(sessionId))
  mobileSessionVisible.value = false
  loading.value.messages = true
  try {
    messages.value = await getAIOpsMessages(sessionId, AIOPS_SESSION_REQUEST_CONFIG)
    resumeMessagePolling(sessionId, messages.value)
    loadDraft(sessionId)
    await nextTick()
    scrollToBottom(true)
    focusComposer()
  } catch (error) {
    if (isAIOpsSessionMissingError(error)) {
      await handleMissingChatSession(sessionId)
      return
    }
    ElMessage.error(error?.response?.data?.detail || '加载会话消息失败')
    throw error
  } finally {
    loading.value.messages = false
  }
}

async function handleCreateSession() {
  try {
    const session = await createAIOpsSession({ title: '' })
    sessions.value.unshift(session)
    messages.value = []
    await selectSession(session.id)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '创建会话失败')
  }
}

async function ensureSession() {
  if (currentSessionId.value) return currentSessionId.value
  const session = await createAIOpsSession({ title: '' })
  sessions.value.unshift(session)
  currentSessionId.value = session.id
  localStorage.setItem(STORAGE_SESSION_KEY, String(session.id))
  messages.value = []
  return session.id
}

async function handleSend() {
  if (!composer.value.trim() || loading.value.send || loading.value.poll) return
  if (authStore.currentUser?.is_demo_account) {
    ElMessage.warning(DEMO_CHAT_DISABLED_MESSAGE)
    return
  }

  const rawContent = composer.value
  const sessionId = await ensureSession()
  const content = buildQuestionPayload(rawContent)

  composer.value = ''
  persistDraft(sessionId, '')
  loading.value.send = true
  pendingAssistantMessage.value = {
    localKey: `pending-${Date.now()}`,
    role: 'assistant',
    pending: true,
    content: '正在分析平台数据，请稍等...',
    created_at: new Date().toISOString(),
  }

  await nextTick()
  scrollToBottom(true)

  try {
    const response = await sendAIOpsMessageAsync(sessionId, {
      content,
      analysis_only: effectiveAnalysisOnly.value,
    }, AIOPS_SESSION_REQUEST_CONFIG)
    messages.value.push(response.user_message)
    messages.value.push(response.assistant_message)
    pendingAssistantMessage.value = null
    await refreshSessionListOnly()
    startMessagePolling(sessionId, response.assistant_message?.id)
    await nextTick()
    scrollToBottom(true)
    focusComposer()
  } catch (error) {
    composer.value = rawContent
    persistDraft(sessionId, rawContent)
    if (isAIOpsSessionMissingError(error)) {
      await handleMissingChatSession(sessionId)
      return
    }
    ElMessage.error(error?.response?.data?.detail || '发送失败，请稍后重试')
  } finally {
    loading.value.send = false
    pendingAssistantMessage.value = null
  }
}

async function handleConfirmAction(action) {
  try {
    const result = await confirmAIOpsAction(action.id)
    if (result?.task_draft) {
      sessionStorage.setItem('sxdevops.task-center.prefill-draft', JSON.stringify(result.task_draft))
      ElMessage.success(`已载入任务草稿 ${result.task_name}`)
      router.push({ path: '/tasks/workbench', query: { aiopsDraft: String(Date.now()) } })
      closePanel()
      return
    }
    ElMessage.success(`已创建任务 ${result.task_name}`)
    await selectSession(currentSessionId.value)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '确认执行失败')
  }
}

async function handleDeleteSession(session) {
  if (!session?.id) return
  try {
    await ElMessageBox.confirm(`确认删除会话《${session.title || '新会话'}》吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    loading.value.deleteSession = session.id
    await deleteAIOpsSession(session.id, AIOPS_SESSION_REQUEST_CONFIG)
    const wasCurrent = currentSessionId.value === session.id
    if (currentSessionId.value === session.id) {
      stopMessagePolling()
      currentSessionId.value = null
      localStorage.removeItem(STORAGE_SESSION_KEY)
      messages.value = []
      loadDraft(null)
    }
    await refreshSessionListOnly()
    if (!sessions.value.length) {
      messages.value = []
      loadDraft(null)
      ElMessage.success('会话已删除')
      return
    }
    if (!wasCurrent && currentSessionId.value && sessions.value.some(item => item.id === currentSessionId.value)) {
      await selectSession(currentSessionId.value)
      ElMessage.success('会话已删除')
      return
    }
    await selectSession(sessions.value[0].id)
    ElMessage.success('会话已删除')
  } catch (error) {
    if (isAIOpsSessionMissingError(error)) {
      await handleMissingChatSession(session.id)
      return
    }
    ElMessage.error(error?.response?.data?.detail || '删除会话失败')
  } finally {
    loading.value.deleteSession = null
  }
}

async function handleCancelAction(action) {
  try {
    await cancelAIOpsAction(action.id)
    ElMessage.success('已取消待执行动作')
    await selectSession(currentSessionId.value)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '取消动作失败')
  }
}

function jumpToCitation(citation) {
  if (!citation?.path) return
  router.push({ path: citation.path, query: citation.query || {} })
  closePanel()
}

function openAIOpsConfig() {
  router.push('/aiops/config')
  closePanel()
}

function applySuggestedQuestion(text) {
  composer.value = text
  persistDraft()
  focusComposer()
}

async function chooseEnvironmentCandidate(message, index, candidate) {
  if (!candidate?.name || loading.value.send || loading.value.poll) return
  const previousPrompt = resolveReusablePrompt(index, message)
    .replace(/^只做分析，不要执行：/, '')
    .trim()
  composer.value = previousPrompt
    ? `使用${candidate.name}环境继续分析：${previousPrompt}`
    : `使用${candidate.name}环境继续分析`
  persistDraft()
  await nextTick()
  await handleSend()
}

function clearDraft() {
  composer.value = ''
  persistDraft(currentSessionId.value, '')
  focusComposer()
}

function handleComposerKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    if (embedded.value) {
      composerRef.value?.blur?.()
      return
    }
    closePanel()
    return
  }
  if (event.key !== 'Enter') return
  if (event.shiftKey) return
  event.preventDefault()
  handleSend()
}

function scrollToBottom(force = false) {
  const el = messageListRef.value
  if (!el) return
  if (!force) {
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120
    if (!nearBottom && !loading.value.send) return
  }
  el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
}

async function copyMessage(content) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(content || '')
      ElMessage.success('已复制消息')
      return
    }
    throw new Error('clipboard unavailable')
  } catch (error) {
    ElMessage.error('当前环境不支持复制，请手动选择文本')
  }
}

function reuseMessage(content) {
  composer.value = content || ''
  persistDraft()
  focusComposer()
}

function resolveReusablePrompt(index, message) {
  if (message.role === 'user') return message.content || ''
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    if (renderMessages.value[cursor]?.role === 'user') {
      return renderMessages.value[cursor].content || ''
    }
  }
  return ''
}

function openTaskCenter() {
  router.push('/tasks/workbench')
  closePanel()
}

async function handleOpenRequest() {
  if (embedded.value) return
  resetFabPosition()
  visible.value = true
  localStorage.setItem(STORAGE_VISIBLE_KEY, '1')
  if (!bootstrap.value.enabled && !loading.value.bootstrap) {
    await fetchBootstrap()
  }
  if (!sessions.value.length && bootstrap.value.enabled) {
    await fetchSessions()
    return
  }
  loadDraft()
  if (currentSessionId.value) {
    resumeMessagePolling(currentSessionId.value, messages.value)
  }
  await nextTick()
  scrollToBottom(true)
  focusComposer()
}

function closePanel() {
  if (embedded.value) return
  visible.value = false
  mobileSessionVisible.value = false
  localStorage.setItem(STORAGE_VISIBLE_KEY, '0')
}

function handleGlobalKeydown(event) {
  if (embedded.value) return
  if (event.key !== 'Escape' || !visible.value) return
  if (mobileSessionVisible.value) {
    mobileSessionVisible.value = false
    return
  }
  closePanel()
}

async function toggleVisible() {
  if (embedded.value) return
  if (ignoreNextFabClick) {
    ignoreNextFabClick = false
    return
  }
  if (!visible.value) {
    resetFabPosition()
  }
  visible.value = !visible.value
  localStorage.setItem(STORAGE_VISIBLE_KEY, visible.value ? '1' : '0')
  if (visible.value) {
    if (!sessions.value.length) {
      await fetchSessions()
    } else {
      loadDraft()
      if (currentSessionId.value) {
        resumeMessagePolling(currentSessionId.value, messages.value)
      }
      await nextTick()
      scrollToBottom(true)
      focusComposer()
    }
  } else {
    mobileSessionVisible.value = false
  }
}

watch(() => renderMessages.value.length, async () => {
  await nextTick()
  scrollToBottom()
})

watch(renderMessages, value => {
  syncProcessCardState(value)
  syncResponseBlockState(value)
}, { deep: true, immediate: true })

watch(analysisOnly, value => {
  localStorage.setItem(STORAGE_ANALYSIS_KEY, value ? '1' : '0')
})

watch(composer, value => {
  persistDraft(currentSessionId.value, value)
})

watch(visible, value => {
  if (value) {
    nextTick(() => {
      focusComposer()
    })
  } else {
    }
})

onMounted(async () => {
  if (!authStore.isAuthenticated) return
  window.addEventListener('resize', handleResize)
  if (!embedded.value) {
    window.addEventListener('keydown', handleGlobalKeydown)
    window.addEventListener('sxdevops-aiops-open', handleOpenRequest)
  }
  await fetchBootstrap()
  if ((embedded.value || visible.value) && bootstrap.value.enabled) {
    await fetchSessions()
    await nextTick()
    scrollToBottom(true)
    focusComposer()
  }
})

onBeforeUnmount(() => {
  stopMessagePolling()
  cleanupFabPointerListeners()
  window.removeEventListener('resize', handleResize)
  if (!embedded.value) {
    window.removeEventListener('keydown', handleGlobalKeydown)
    window.removeEventListener('sxdevops-aiops-open', handleOpenRequest)
  }
})
</script>

<style scoped>
.aiops-widget{position:fixed;right:24px;bottom:24px;z-index:80}
.aiops-layer{position:fixed;inset:0;z-index:79;overflow:hidden}
.aiops-backdrop{position:absolute;inset:0;border:none;background:rgba(15,23,42,.12);backdrop-filter:blur(4px);cursor:pointer}
.aiops-widget.embedded{position:relative;inset:auto;z-index:1;width:100%;height:100%;min-height:0}
.aiops-layer.embedded{position:relative;inset:auto;z-index:1;width:100%;height:100%;min-height:0;overflow:hidden}
.aiops-fab{position:relative;z-index:81;display:flex;align-items:center;gap:9px;min-width:132px;height:58px;padding:7px 12px 7px 7px;border:none;border-radius:999px;background:linear-gradient(135deg,#ffffff 0%,#f7fbff 100%);box-shadow:0 12px 24px rgba(59,130,246,.12);cursor:grab;border:1px solid #bdd5fb;transition:transform .18s ease,box-shadow .18s ease;touch-action:none;user-select:none}
.aiops-fab:hover{transform:translateY(-2px);box-shadow:0 16px 30px rgba(59,130,246,.16)}
.aiops-fab.dragging{cursor:grabbing;transform:none;box-shadow:0 18px 34px rgba(59,130,246,.2)}
.aiops-fab-ring{position:absolute;inset:-2px;border-radius:999px;border:1px solid rgba(59,130,246,.16);box-shadow:0 0 0 1px rgba(255,255,255,.92);pointer-events:none}
.aiops-fab-core{position:relative;display:inline-flex;align-items:center;justify-content:center;width:42px;height:42px;border-radius:20px;background:linear-gradient(145deg,#eef5ff 0%,#f6fbff 100%);box-shadow:inset 0 1px 0 rgba(255,255,255,.96),0 8px 16px rgba(59,130,246,.08)}
.aiops-fab-avatar{width:30px;height:30px;display:block}
.aiops-fab-label{display:flex;flex-direction:column;align-items:flex-start;line-height:1.1;position:relative;z-index:1}
.aiops-fab-label strong{font-size:13px;color:#0f172a}
.aiops-fab-label small{margin-top:2px;font-size:10px;color:#64748b}
.aiops-fab-dot{position:absolute;top:9px;right:10px;width:8px;height:8px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 3px rgba(255,255,255,.96),0 0 0 5px rgba(34,197,94,.1)}
.aiops-panel{--aiops-session-width:260px;--aiops-chat-base-width:836px;position:absolute;right:24px;bottom:84px;width:min(1096px,calc(100vw - var(--sidebar-width,188px) - 40px));max-width:calc(100vw - var(--sidebar-width,188px) - 40px);height:min(800px,calc(100vh - 104px));display:flex;flex-direction:column;background:linear-gradient(180deg,#fff 0%,#f8fbff 100%);border:1px solid #dbe4f0;border-radius:24px;box-shadow:0 26px 56px rgba(15,23,42,.18);overflow:hidden}
.aiops-panel.embedded{--aiops-session-width:280px;position:relative;right:auto;bottom:auto;width:100%;max-width:none;height:100%;min-height:0;border-radius:20px;box-shadow:0 14px 32px rgba(15,23,42,.06)}
.aiops-panel-header{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;border-bottom:1px solid #e2e8f0;background:linear-gradient(135deg,#fff7ed 0%,#f0f9ff 100%)}
.header-copy{min-width:0;flex:1}
.aiops-title-row{display:flex;align-items:center;gap:8px;min-width:0;min-height:34px}
.aiops-header-avatar{width:32px;height:32px;display:block;flex:0 0 auto}
.aiops-title{font-size:16px;font-weight:700;color:#0f172a}
.header-badge{padding:3px 8px;border-radius:999px;background:#ecfeff;color:#0f766e;font-size:12px;white-space:nowrap}
.header-badge.runtime{background:#e0f2fe;color:#075985}
.header-badge.runtime.safe{background:#ecfccb;color:#3f6212}
.aiops-subtitle{min-width:180px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;color:#64748b;line-height:1.4;padding-top:1px}
.aiops-header-actions{display:flex;align-items:center;gap:8px;min-height:34px}
.aiops-panel-body{display:grid;grid-template-columns:min(var(--aiops-session-width),max(204px,calc(100% - var(--aiops-chat-base-width)))) minmax(0,1fr);flex:1;min-height:0}
.aiops-panel.embedded .aiops-panel-body{grid-template-columns:var(--aiops-session-width) minmax(0,1fr)}
.aiops-session-list{padding:10px;border-right:1px solid #e2e8f0;background:#f8fafc;overflow:auto;-webkit-overflow-scrolling:touch}
.session-list-head{
  position:relative;
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:8px;
  margin-bottom:8px;
  padding:0 4px 10px;
  color:#475569;
  font-size:12px;
}
.session-list-head::after{
  content:'';
  position:absolute;
  left:4px;
  right:4px;
  bottom:0;
  height:1px;
  background:linear-gradient(90deg, rgba(226,232,240,0), rgba(191,219,254,.9) 14%, rgba(226,232,240,.95) 50%, rgba(191,219,254,.9) 86%, rgba(226,232,240,0));
}
.session-head-title{display:flex;align-items:center;gap:6px;min-width:0;font-weight:700}
.session-list-title{color:#334155}
.aiops-session-item{position:relative;display:flex;align-items:center;gap:6px;padding:0 4px 0 0;border-radius:12px;background:transparent;color:#334155;margin-bottom:6px;transition:background .18s ease,box-shadow .18s ease,transform .18s ease}
.aiops-session-item:hover{background:#fff;transform:translateY(-1px)}
.aiops-session-item.active{background:#fff;box-shadow:0 10px 20px rgba(15,23,42,.08)}
.session-select-btn{flex:1;min-width:0;text-align:left;padding:10px 10px 10px 12px;border:none;background:transparent;cursor:pointer;color:inherit}
.session-delete-btn{position:absolute;top:50%;right:6px;transform:translateY(-50%);width:24px;height:24px;border:none;opacity:0;pointer-events:none;transition:opacity .16s ease,background .16s ease,color .16s ease}
.aiops-session-item:hover .session-delete-btn{opacity:1;pointer-events:auto}
.session-delete-btn:hover{background:#fee2e2;color:#b91c1c}
.session-title{display:block;font-size:12px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.session-empty{font-size:12px;color:#64748b}
.aiops-chat-main{display:flex;flex-direction:column;min-width:0;min-height:0}
.chat-toolbar{display:flex;align-items:center;justify-content:space-between;padding:6px 12px;border-bottom:1px solid #edf2f7;background:rgba(255,255,255,.82)}
.chat-toolbar-left,.chat-toolbar-right{display:flex;align-items:center;gap:10px;min-width:0}
.toolbar-chip{border:none;border-radius:999px;padding:6px 11px;background:#dbeafe;color:#1d4ed8;cursor:pointer;font-size:12px;font-weight:600}
.session-indicator{display:flex;flex-direction:column;min-width:0;max-width:220px;line-height:1.1}
.session-indicator-label{font-size:12px;font-weight:700;color:#334155;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.environment-chip{display:inline-flex;align-items:center;height:24px;padding:0 8px;border-radius:6px;background:#ecfdf5;border:1px solid #bbf7d0;color:#047857;font-size:12px;font-weight:700;white-space:nowrap}
.environment-chip.empty{background:#fff7ed;border-color:#fed7aa;color:#c2410c}
.page-context-chip{background:#eff6ff;border-color:#bfdbfe;color:#1d4ed8}
.analysis-toggle{display:flex;align-items:center;gap:8px;font-size:12px;color:#334155}
.toolbar-hint{font-size:12px;color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.quick-palette{padding:6px 12px 0}
.aiops-quick-questions,.aiops-secondary-actions{display:flex;gap:8px;flex-wrap:wrap}
.quick-chip{border:none;border-radius:999px;padding:6px 10px;cursor:pointer;transition:transform .18s ease,box-shadow .18s ease;font-size:12px}
.quick-chip{background:#e0f2fe;color:#075985}
.quick-chip:hover{transform:translateY(-1px);box-shadow:0 8px 20px rgba(15,23,42,.08)}
.message-stage{position:relative;flex:1;min-height:0;overflow:hidden}
.aiops-message-list{height:100%;overflow:auto;padding:10px 12px;display:flex;flex-direction:column;gap:8px;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;touch-action:pan-y}
.message-empty{margin:auto;max-width:380px;text-align:center}
.empty-title{font-size:16px;font-weight:700;color:#0f172a}
.empty-copy{margin-top:8px;color:#64748b;line-height:1.6;font-size:12px}
.message-item{display:flex;flex-direction:column;gap:3px;max-width:92%}
.message-item.user{align-self:flex-end}
.message-item.pending{opacity:.82}
.message-meta{display:flex;align-items:center;gap:6px;color:#64748b;font-size:11px}
.message-item.user .message-meta{justify-content:flex-end}
.message-bubble{padding:8px 12px;border-radius:14px;background:#fff;border:1px solid #e2e8f0;box-shadow:0 6px 14px rgba(15,23,42,.05)}
.message-item.user .message-bubble{background:linear-gradient(135deg,#dbeafe,#f0f9ff)}
.message-content{font-size:13px;line-height:1.5;color:#0f172a;word-break:break-word}
.user-content{white-space:pre-wrap}
.rich-heading{font-size:13px;font-weight:700;color:#0f172a;margin-bottom:6px}
.rich-paragraph{white-space:pre-wrap;color:#334155;font-size:13px}
.rich-paragraph + .rich-paragraph{margin-top:8px}
.rich-list{margin:0;padding-left:16px;color:#334155;font-size:13px}
.rich-list + .rich-paragraph,.rich-paragraph + .rich-list,.rich-heading + .rich-list,.rich-list + .rich-heading{margin-top:10px}
.rich-list-item + .rich-list-item{margin-top:8px}
.rich-list-title{font-weight:600;color:#1e293b;font-size:13px}
.rich-sublist{margin:4px 0 0;padding-left:16px;color:#475569;font-size:12px}
.rich-inline-code{display:inline-block;margin:0 2px;padding:1px 6px;border-radius:6px;background:#eff6ff;color:#1d4ed8;font-size:12px;font-family:Consolas,Monaco,monospace}
.rich-inline-link{color:#2563eb;text-decoration:none}
.rich-inline-link:hover{text-decoration:underline}
.rich-code{margin:8px 0 0;padding:8px 10px;border-radius:10px;background:#0f172a;color:#e2e8f0;font-size:11px;line-height:1.5;white-space:pre-wrap;overflow:auto}
.response-block-list{display:flex;flex-direction:column;gap:8px;margin-top:10px}
.response-block-card{padding:9px 10px;border-radius:12px;border:1px solid #dbe4f0;background:linear-gradient(180deg,#fbfdff 0%,#fff 100%);box-shadow:0 4px 12px rgba(15,23,42,.035)}
.response-block-card.type-tool_trace{background:#f8fafc;border-color:#e2e8f0}
.response-block-card.type-context_summary{background:linear-gradient(180deg,#f8fbff 0%,#fff 100%);border-color:#dbeafe}
.response-block-card.type-context_form{background:linear-gradient(180deg,#fffaf5 0%,#fff 100%);border-color:#fed7aa}
.response-block-card.type-query_suggestion{background:linear-gradient(180deg,#f8fbff 0%,#fff 100%);border-color:#bfdbfe}
.response-block-card.type-risk_notice,.response-block-card.type-approval_form{background:linear-gradient(180deg,#fffaf5 0%,#fff 100%);border-color:#fed7aa}
.response-block-card.type-k8s_action{background:linear-gradient(180deg,#f7fbff 0%,#fff 100%);border-color:#d7e8ff}
.response-block-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.response-block-headline{min-width:0;display:flex;flex-direction:column;gap:3px}
.response-block-title{font-size:12px;font-weight:700;color:#1e293b}
.response-block-summary{font-size:11px;line-height:1.5;color:#64748b;word-break:break-word}
.response-block-card.is-collapsed .response-block-head{align-items:center}
.response-block-card.is-collapsed .response-block-headline{flex-direction:row;align-items:center;gap:8px;white-space:nowrap}
.response-block-card.is-collapsed .response-block-title{flex:0 0 auto;max-width:42%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.response-block-card.is-collapsed .response-block-summary{flex:1 1 auto;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;word-break:normal}
.response-block-head-actions{display:flex;align-items:center;gap:8px;flex:0 0 auto}
.response-block-badge{flex:0 0 auto;padding:2px 7px;border-radius:999px;background:#eff6ff;color:#1d4ed8;font-size:10px;font-weight:700}
.response-block-card.type-risk_notice .response-block-badge,.response-block-card.type-approval_form .response-block-badge{background:#fff7ed;color:#c2410c}
.response-block-toggle{border:none;padding:2px 0;background:transparent;color:#64748b;font-size:11px;cursor:pointer}
.response-block-toggle:hover{color:#334155}
.response-block-content{margin-top:8px}
.response-block-metric-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;margin-top:8px}
.response-block-metric{padding:7px 8px;border-radius:10px;background:rgba(255,255,255,.72);border:1px solid rgba(226,232,240,.9);display:flex;flex-direction:column;gap:3px}
.response-block-metric span{font-size:10px;color:#64748b}
.response-block-metric strong{font-size:12px;color:#1f2937}
.response-block-field-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;margin-top:8px}
.response-block-field{padding:7px 8px;border-radius:10px;background:rgba(255,255,255,.72);border:1px dashed rgba(251,146,60,.36);display:flex;flex-direction:column;gap:3px;min-width:0}
.response-block-field span{font-size:10px;color:#9a3412}
.response-block-field strong{font-size:12px;color:#7c2d12;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.response-block-command{margin-top:8px;max-height:320px;overflow:auto;padding:8px 10px;border-radius:10px;background:#111827;color:#f8fafc;font-size:11px;line-height:1.5;white-space:pre;word-break:normal}
.response-block-trace{display:flex;flex-direction:column;gap:6px;margin-top:8px}
.response-block-trace-item,.response-block-item{display:flex;align-items:flex-start;gap:8px;min-width:0}
.response-block-trace-dot,.response-block-item-dot{width:8px;height:8px;border-radius:50%;margin-top:6px;background:#94a3b8;flex:0 0 auto}
.response-block-trace-dot.success{background:#22c55e}
.response-block-trace-dot.failed{background:#ef4444}
.response-block-trace-body,.response-block-item-body{min-width:0;flex:1}
.response-block-trace-name,.response-block-item-text{font-size:12px;font-weight:600;color:#334155;word-break:break-word}
.response-block-trace-detail,.response-block-item-detail{margin-top:2px;font-size:11px;line-height:1.5;color:#64748b;word-break:break-word}
.response-block-chip-list{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.response-block-chip{border:1px solid #bfdbfe;border-radius:999px;background:#fff;color:#1d4ed8;padding:4px 8px;font-size:11px;font-weight:600;cursor:pointer;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.response-block-chip:hover{background:#eff6ff}
.response-block-item-list{display:flex;flex-direction:column;gap:7px;margin-top:8px}
.response-block-actions{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:8px;padding-top:7px;border-top:1px dashed #e2e8f0}
.response-block-action-btn{height:24px;padding:3px 8px;border-radius:8px;color:#334155}
.response-block-action-btn :deep(.el-icon){margin-right:3px}
.assistant-followup-line{margin-top:8px;color:#475569;font-size:12px;line-height:1.5}
.citation-row{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.citation-chip{border:none;border-radius:999px;padding:4px 8px;background:#ecfeff;color:#0f766e;cursor:pointer;font-size:11px}
.pending-action-card{margin-top:10px;padding:10px;border-radius:12px;background:#fff7ed;border:1px solid #fdba74}
.pending-title-row{display:flex;align-items:center;justify-content:space-between;gap:8px}
.pending-title{font-weight:700;color:#9a3412}
.pending-risk{padding:4px 8px;border-radius:999px;background:#ffedd5;color:#9a3412;font-size:12px}
.pending-risk.high,.pending-risk.critical{background:#fee2e2;color:#b91c1c}
.pending-meta,.pending-result,.pending-hint{margin-top:6px;font-size:11px;color:#7c2d12}
.pending-hint{padding:6px 8px;border-radius:10px;background:rgba(255,255,255,.7);border:1px dashed rgba(194,65,12,.18)}
.pending-detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:10px}
.pending-detail-item{padding:8px 10px;border-radius:12px;background:rgba(255,255,255,.7);display:flex;flex-direction:column;gap:4px}
.pending-detail-item span{font-size:12px;color:#9a3412}
.pending-detail-item strong{font-size:12px;color:#7c2d12}
.pending-command{margin-top:8px;max-height:320px;overflow:auto;padding:8px 10px;border-radius:10px;background:#111827;color:#f8fafc;font-size:11px;line-height:1.5;white-space:pre;word-break:normal}
.pending-actions{display:flex;gap:8px;margin-top:10px}
.message-state-card{margin-top:10px;padding:8px 10px;border-radius:12px;background:#f8fafc;border:1px solid #cbd5e1;color:#475569;font-size:11px;line-height:1.5}
.message-error-card{display:flex;flex-direction:column;gap:8px;padding:10px 12px;border-radius:14px;background:linear-gradient(180deg,#fffaf5 0%,#fff 100%);border:1px solid #fed7aa}
.message-error-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.message-error-badge{display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;background:#fff7ed;color:#c2410c;font-size:11px;font-weight:600}
.message-error-tag{display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;background:#f8fafc;color:#64748b;font-size:11px}
.message-error-title{font-size:14px;font-weight:700;color:#9a3412}
.message-error-desc{font-size:12px;line-height:1.6;color:#7c2d12}
.message-error-detail{padding:8px 10px;border-radius:10px;background:rgba(255,255,255,.78);border:1px solid #fdba74;font-size:11px;line-height:1.5;color:#9a3412;white-space:pre-wrap;word-break:break-word}
.message-error-actions{display:flex;justify-content:flex-start}
.environment-candidate-list{display:flex;flex-wrap:wrap;gap:6px}
.environment-candidate-btn{display:inline-flex;align-items:center;gap:6px;max-width:100%;border:1px solid #fdba74;border-radius:999px;background:#fff;color:#9a3412;padding:5px 9px;font-size:11px;cursor:pointer}
.environment-candidate-btn:hover{background:#fff7ed}
.environment-candidate-btn:disabled{cursor:not-allowed;opacity:.58}
.environment-candidate-btn strong{font-size:12px;color:#7c2d12}
.environment-candidate-btn span{max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#c2410c}
.analysis-process-card{margin-bottom:10px;padding:8px 10px;border-radius:12px;background:#f8fafc;border:1px solid #e2e8f0}
.analysis-process-card.active{border-color:#dbe4f0;background:#f8fafc}
.analysis-process-head{display:flex;align-items:center;justify-content:space-between;gap:8px}
.analysis-process-headline{display:flex;align-items:center;gap:8px;min-width:0}
.analysis-process-title{font-size:12px;font-weight:600;color:#334155}
.analysis-process-inline-summary{font-size:11px;color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.analysis-process-actions{display:flex;align-items:center;gap:8px}
.analysis-process-status{padding:2px 7px;border-radius:999px;background:#f1f5f9;color:#64748b;font-size:11px}
.analysis-process-status.pending{background:#fff7ed;color:#9a3412}
.analysis-process-status.running,.analysis-process-status.streaming{background:#eff6ff;color:#1d4ed8}
.analysis-process-status.completed{background:#f1f5f9;color:#64748b}
.analysis-process-status.failed{background:#fef2f2;color:#b91c1c}
.analysis-process-toggle{border:none;padding:2px 0;background:transparent;color:#64748b;font-size:11px;cursor:pointer}
.analysis-process-toggle:hover{color:#334155}
.analysis-process-content{margin-top:8px}
.analysis-process-summary{margin-top:6px;font-size:12px;color:#475569;line-height:1.5}
.analysis-process-list{display:flex;flex-direction:column;gap:8px;margin-top:8px}
.analysis-process-item{display:flex;align-items:flex-start;gap:8px}
.analysis-process-dot{width:8px;height:8px;border-radius:50%;margin-top:5px;background:#94a3b8;flex:0 0 auto}
.analysis-process-dot.pending{background:#f59e0b}
.analysis-process-dot.running,.analysis-process-dot.streaming{background:#3b82f6}
.analysis-process-dot.completed{background:#22c55e}
.analysis-process-dot.failed{background:#ef4444}
.analysis-process-body{min-width:0;flex:1}
.analysis-process-item-head{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:10px;color:#94a3b8}
.analysis-process-item-head strong{font-size:12px;font-weight:600;color:#334155}
.analysis-process-item-detail{margin-top:2px;font-size:11px;color:#64748b;line-height:1.5}
.tool-event-list{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.tool-event-item{display:flex;align-items:center;gap:6px;padding:4px 8px;border-radius:999px;background:#ffffff;border:1px solid #e2e8f0;font-size:11px;color:#334155}
.tool-event-name{font-weight:600;color:#475569}
.tool-event-detail{color:#64748b}
.message-actions{display:flex;gap:2px;justify-content:flex-end;margin-top:8px;padding-top:6px;border-top:1px dashed #e2e8f0}
.aiops-composer{padding:8px 12px;border-top:1px solid #e2e8f0;background:#fff}
.aiops-composer :deep(.el-textarea__inner){min-height:52px!important;padding:7px 10px;font-size:13px;line-height:1.45}
.aiops-composer :deep(.el-input__count){line-height:1;font-size:10px;bottom:4px;right:8px}
.aiops-composer :deep(.el-button){height:28px;padding:5px 11px;font-size:12px}
.aiops-toolbar-btn{height:28px;padding:5px 10px;border-radius:8px;border:1px solid #dbe4f0;background:#fff;color:#334155;box-shadow:0 1px 2px rgba(15,23,42,.04)}
.aiops-toolbar-btn:hover{border-color:#bfdbfe;background:#f8fbff;color:#1d4ed8}
.aiops-toolbar-btn:disabled{background:#f8fafc;border-color:#e2e8f0;color:#94a3b8;box-shadow:none}
.aiops-send-btn{height:28px;padding:5px 12px;border-radius:8px}
.aiops-toolbar-btn :deep(.el-icon),
.aiops-send-btn :deep(.el-icon){margin-right:4px}
.composer-actions{display:flex;align-items:center;justify-content:space-between;margin-top:4px}
.composer-meta{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.composer-tip{font-size:10px;color:#64748b;line-height:1.2}
.composer-action-group{display:flex;align-items:center;gap:6px}
.mobile-session-sheet{display:none}
:global(.aiops-session-tooltip){
  max-width:320px;
  padding:0;
  border:none;
  border-radius:18px;
  background:transparent;
  box-shadow:none;
  overflow:visible;
}
:global(.aiops-session-tooltip .el-popper__content){
  padding:0;
  background:transparent;
  border-radius:18px;
}
:global(.aiops-session-tooltip .el-popper__arrow::before){
  background:#f7fbff;
  border-color:rgba(148,163,184,.18);
}
.aiops-session-tooltip-card{
  position:relative;
  padding:12px 14px 13px;
  border-radius:18px;
  border:1px solid rgba(191,219,254,.72);
  background:
    radial-gradient(circle at top right, rgba(59,130,246,.10), transparent 36%),
    linear-gradient(135deg, rgba(255,247,237,.98) 0%, rgba(240,249,255,.98) 100%);
  box-shadow:
    0 18px 40px rgba(15,23,42,.14),
    0 2px 8px rgba(59,130,246,.08);
  backdrop-filter:blur(10px);
  overflow:hidden;
}
.aiops-session-tooltip-card::before{
  content:'';
  position:absolute;
  inset:0;
  border-radius:inherit;
  background:linear-gradient(135deg, rgba(255,255,255,.6), transparent 52%);
  pointer-events:none;
}
.aiops-session-tooltip-title{
  position:relative;
  color:#0f172a;
  font-size:12px;
  line-height:1.7;
  white-space:normal;
  word-break:break-word;
}
.aiops-panel-enter-active,.aiops-panel-leave-active{transition:all .18s ease}
.aiops-panel-enter-from,.aiops-panel-leave-to{opacity:0;transform:translateY(10px)}
.aiops-sheet-enter-active,.aiops-sheet-leave-active{transition:all .18s ease}
.aiops-sheet-enter-from,.aiops-sheet-leave-to{opacity:0;transform:translateY(12px)}
@media (max-width: 920px){
  .aiops-widget{right:12px;bottom:12px}
  .aiops-fab{min-width:118px;height:52px;padding:6px 10px 6px 6px}
  .aiops-fab-core{width:38px;height:38px;border-radius:18px}
  .aiops-fab-avatar{width:26px;height:26px}
  .aiops-panel{right:12px;bottom:80px;width:min(720px,calc(100vw - var(--sidebar-width,188px) - 24px));max-width:calc(100vw - var(--sidebar-width,188px) - 24px);height:min(86vh,calc(100vh - 100px))}
  .aiops-panel.embedded{width:100%;height:100%;min-height:0}
  .aiops-panel-body{grid-template-columns:1fr}
  .aiops-session-list{display:none}
  .pending-detail-grid{grid-template-columns:1fr}
  .response-block-metric-grid{grid-template-columns:1fr}
  .response-block-field-list{grid-template-columns:1fr}
  .response-block-actions{align-items:stretch}
  .chat-toolbar{flex-direction:column;align-items:flex-start;gap:6px}
  .chat-toolbar-left,.chat-toolbar-right{width:100%;justify-content:space-between}
  .toolbar-hint{max-width:100%}
  .session-indicator{max-width:none;flex:1}
  .mobile-session-sheet{display:flex;position:absolute;left:12px;right:12px;bottom:12px;max-height:45vh;flex-direction:column;border:1px solid #dbe4f0;border-radius:22px;background:#fff;box-shadow:0 20px 48px rgba(15,23,42,.24);overflow:hidden}
  .mobile-session-head{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid #e2e8f0;background:#f8fafc;min-height:48px}
  .mobile-session-body{padding:12px;overflow:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;touch-action:pan-y}
  .aiops-composer{padding:8px 12px}
  .aiops-toolbar-btn,.aiops-send-btn{height:30px}
  .composer-actions{flex-direction:column;align-items:stretch;gap:6px}
  .composer-meta{justify-content:space-between;gap:8px}
  .composer-action-group{justify-content:flex-end}
}
@media (max-width: 760px){
  .aiops-panel{right:8px;width:calc(100vw - var(--sidebar-collapsed-width,68px) - 16px);max-width:calc(100vw - var(--sidebar-collapsed-width,68px) - 16px)}
}
</style>







