/**
 * 余额结果的「怎么报」：级别、措辞、要不要重复报。
 *
 * 钉住三件事：
 *   ① 未登记服务商（unsupported）是配置事实，不是失败——按 info 记，且只记一次；
 *   ② 缺凭证与抓取失败是真问题——按 warn 记，且每次都记；
 *   ③ 成功照旧按 info 记。
 *
 * 用 Node 内置 test runner（node:test），不引入任何 npm 依赖。
 *
 * @module dsh-pet/src/host/balance-report.test
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { createBalanceReporter } from './balance/report.ts';
import type { BalanceResult } from './balance/types.ts';

/** 收集日志行：级别与内容都留着，便于断言「说了几次、说了什么」。 */
function collect(): { log: { info: (m: string) => void; warn: (m: string) => void }; lines: { level: string; text: string }[] } {
  const lines: { level: string; text: string }[] = [];
  return {
    lines,
    log: {
      info: (m: string) => lines.push({ level: 'info', text: m }),
      warn: (m: string) => lines.push({ level: 'warn', text: m }),
    },
  };
}

const unsupported = (provider: string): BalanceResult => ({ ok: false, provider, reason: 'unsupported' });

describe('余额上报 —— 未登记服务商不是失败', () => {
  test('unsupported：按 info 记一条，措辞说清「不是错误」', () => {
    const { log, lines } = collect();
    createBalanceReporter(log)(unsupported('minimax-cn'));
    assert.equal(lines.length, 1);
    assert.equal(lines[0].level, 'info', '不是失败，不该用 warn');
    assert.match(lines[0].text, /minimax-cn/, '说清是哪个服务商');
    assert.match(lines[0].text, /不是错误/, '说清这不是错误');
    assert.doesNotMatch(lines[0].text, /失败/, '措辞里不该出现「失败」');
  });

  test('unsupported：同一个服务商只说一次，后台轮询不再刷屏', () => {
    const { log, lines } = collect();
    const report = createBalanceReporter(log);
    report(unsupported('minimax-cn'));
    report(unsupported('minimax-cn'));
    report(unsupported('minimax-cn'));
    assert.equal(lines.length, 1, '同一个服务商只记一条');
  });

  test('unsupported：换了另一个服务商再说一次', () => {
    const { log, lines } = collect();
    const report = createBalanceReporter(log);
    report(unsupported('minimax-cn'));
    report(unsupported('onerway'));
    assert.equal(lines.length, 2, '换服务商算新的事实，要再说一次');
    assert.match(lines[1].text, /onerway/);
  });
});

describe('余额上报 —— 真问题每次都报', () => {
  test('credential-missing 与 fetch-error：按 warn 记，且重复出现时照样记', () => {
    const { log, lines } = collect();
    const report = createBalanceReporter(log);
    const missing: BalanceResult = { ok: false, provider: 'deepseek-official', reason: 'credential-missing' };
    const broken: BalanceResult = { ok: false, provider: 'opencode-go', reason: 'fetch-error', message: 'HTTP 500' };
    report(missing);
    report(missing);
    report(broken);
    assert.equal(lines.length, 3, '每次都记');
    assert.equal(lines[0].level, 'warn');
    assert.equal(lines[1].level, 'warn', '同一个原因重复出现也要记');
    assert.equal(lines[2].level, 'warn');
    assert.match(lines[2].text, /HTTP 500/, '带上原因里的消息');
  });
});

describe('余额上报 —— 成功照旧', () => {
  test('成功：按 info 记，带服务商与形态', () => {
    const { log, lines } = collect();
    createBalanceReporter(log)({
      ok: true,
      provider: 'opencode-go',
      shape: 'windows',
      data: { rolling: 1, weekly: 2, monthly: 3 },
    });
    assert.equal(lines.length, 1);
    assert.equal(lines[0].level, 'info');
    assert.match(lines[0].text, /opencode-go/);
    assert.match(lines[0].text, /windows/);
  });
});
