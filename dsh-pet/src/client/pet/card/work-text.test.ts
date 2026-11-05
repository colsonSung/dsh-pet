/**
 * 工作状态气泡的判定（纯函数契约）：有话才亮，新话才重新亮。
 *
 * 这条规则是「气泡不再常驻」的关键：
 * - 没有任务详情时，工作/思考/整理这些档位不显示气泡（纯氛围不算消息）；
 * - 文案没变就不重新点亮（否则每 tick 亮一次，气泡一直挂着头顶）。
 *
 * 跑法：node --experimental-strip-types --test src/client/pet/card/bubble-slots.test.ts
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { decideWorkText } from './bubble-slots.ts';

describe('工作状态气泡：文案与点亮', () => {
  test('有任务详情 → 显示它，并点亮', () => {
    const d = decideWorkText({
      task: '翻翻 package.json 看看嘛',
      state: 'working',
      configuredText: '正在构建',
      prevText: null,
      stateChanged: true,
    });
    assert.equal(d.text, '翻翻 package.json 看看嘛');
    assert.equal(d.light, true);
  });

  test('没有任务详情 + 工作档位 → 没有文案，也不亮（纯氛围不算消息）', () => {
    const d = decideWorkText({
      task: null,
      state: 'working',
      configuredText: '正在构建',
      prevText: null,
      stateChanged: true,
    });
    assert.equal(d.text, null);
    assert.equal(d.light, false);
  });

  test('没有任务详情 + 思考档位 → 同样不显示', () => {
    const d = decideWorkText({
      task: null,
      state: 'thinking',
      configuredText: '正在想下一步',
      prevText: null,
      stateChanged: true,
    });
    assert.equal(d.text, null);
    assert.equal(d.light, false);
  });

  test('等待确认 / 完成 / 出错 → 状态本身即消息，用档位文案', () => {
    for (const state of ['waiting', 'success', 'error']) {
      const d = decideWorkText({
        task: null,
        state,
        configuredText: '轮到你了',
        prevText: null,
        stateChanged: true,
      });
      assert.equal(d.text, '轮到你了', state);
      assert.equal(d.light, true, state);
    }
  });

  test('文案没变 → 不重新点亮（气泡不会一直挂在头顶）', () => {
    const d = decideWorkText({
      task: '翻翻 package.json 看看嘛',
      state: 'working',
      configuredText: '正在构建',
      prevText: '翻翻 package.json 看看嘛',
      stateChanged: false,
    });
    assert.equal(d.text, '翻翻 package.json 看看嘛');
    assert.equal(d.light, false);
  });

  test('文案变了 → 重新点亮', () => {
    const d = decideWorkText({
      task: '改改 index.ts 啦',
      state: 'working',
      configuredText: '正在构建',
      prevText: '翻翻 package.json 看看嘛',
      stateChanged: false,
    });
    assert.equal(d.light, true);
  });

  test('档位变了但文案没变 → 算一次新消息', () => {
    const d = decideWorkText({
      task: '翻翻 package.json 看看嘛',
      state: 'result',
      configuredText: '这一步过了',
      prevText: '翻翻 package.json 看看嘛',
      stateChanged: true,
    });
    assert.equal(d.light, true);
  });
});
