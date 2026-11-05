/**
 * 余额查询结果的「怎么报」：日志级别、措辞，以及要不要重复报。
 *
 * 背景：服务商分三种情况，后台轮询对它们的处理不该一样。
 *
 * - `unsupported`：这个服务商没有登记余额接口。它是**配置事实**，不是失败——
 *   用户改不了（除非换一个服务商），后台每 30 分钟报一次「失败」只会把日志刷满，
 *   并训练用户忽略告警。所以按 info 记一次就够，之后不再重复。
 * - `credential-missing` / `fetch-error`：真问题，用户能动手修（补凭证、查网络），
 *   一律 warn，且每次都报——重复的告警才有意义，因为它需要用户去处理。
 * - 成功：info，照旧。
 *
 * 「只说一次」的状态放在这里（一个 Set），而不是散在调用方：调用方只管把结果交过来。
 *
 * @module dsh-pet/src/host/balance/report
 */
import type { BalanceResult } from './types.ts';

/** 日志出口的最小面：只要能写 info 与 warn 两级。 */
export type BalanceLogSink = {
  info(message: string): void;
  warn(message: string): void;
};

/**
 * 造一个余额结果上报器。
 *
 * @param log - 日志出口（宿主侧是插件的文件 logger）。
 * @returns 上报函数：把一次查询结果写进日志，并决定要不要重复报。
 */
export function createBalanceReporter(log: BalanceLogSink): (result: BalanceResult) => void {
  // 已经说过「不支持」的服务商：同一个只说一次，换服务商再说。
  const notedUnsupported = new Set<string>();
  return (result: BalanceResult): void => {
    if (result.ok) {
      log.info(`[dsh-pet] 余额刷新成功 provider=${result.provider}（${result.shape}）`);
      return;
    }
    if (result.reason === 'unsupported') {
      if (notedUnsupported.has(result.provider)) return;
      notedUnsupported.add(result.provider);
      log.info(
        `[dsh-pet] 未登记余额服务商 provider=${result.provider}` +
          '：本插件不查该服务商的余额，不是错误',
      );
      return;
    }
    log.warn(
      `[dsh-pet] 余额刷新失败 provider=${result.provider} reason=${result.reason}` +
        (result.message ? ' ' + result.message : ''),
    );
  };
}
