/**
 * 余额不可用时「要不要弹文字说明」的判定。
 *
 * 判定本身无状态：只比对传入的 lastKey，调用方负责保存返回的 key。
 * 两端（浏览器 overlay 与桌面外壳）必须走同一份判定，各写一份必然漂移。
 *
 * @module dsh-pet/src/shared/balance/notice
 */

import type { BalanceNoticeDecision, BalanceState } from './types.ts';

/**
 * 判定本次是否弹气泡，并给出供下次比较的原因 key。
 *
 * 显式请求（`/balance` 命令、桌面「查看余额」菜单）一律弹：用户问了就该有答复，
 * 包括「这个服务商不支持」这件事。
 *
 * 自动轮询只报**用户能动手解决**的问题：
 * - `credential-missing`（缺凭证）与 `fetch-error`（抓取失败）：原因变了就弹一次，
 *   提醒用户去补凭证或查网络；
 * - `unsupported`（该服务商没有登记余额接口）：这是配置事实，用户改不了——
 *   除非换一个服务商。每隔一段时间就弹一句「当前服务商暂不支持余额查询」，
 *   对用户没有任何可执行的动作，只是噪声，所以自动轮询不弹；用户自己问时照弹。
 *
 * @param state - 当前余额状态；只读，本函数不修改它。
 * @param lastKey - 上次提示的原因 key，null 表示尚未提示过。
 * @param explicit - 是否由用户显式请求触发。
 * @returns 是否弹，以及本次要存下的 key（ok 状态为 null）。
 */
export function decideBalanceNotice(
  state: BalanceState,
  lastKey: string | null,
  explicit: boolean,
): BalanceNoticeDecision {
  if (state.ok) return { show: false, key: null };
  const key = state.reason + ':' + state.provider;
  if (explicit) return { show: true, key };
  // 自动轮询：只有「用户改得动」的原因才值得打扰一次。
  if (state.reason === 'unsupported') return { show: false, key };
  return { show: key !== lastKey, key };
}
